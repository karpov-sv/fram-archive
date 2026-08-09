"""Tests for the color-aware magnitudes of the light curve."""

import json

import numpy as np
import pytest

from archive.views_photometry import (
    CLIP_MIN_POINTS, BV_FIT_MIN_POINTS, BV_MIN_PAIRS, CAL_COLOR_SPREAD, COLOR_TERM_MIN_POINTS,
    COLOR_TERM_MIN_SIGNIFICANCE, build_lc, color_aware_mags,
    clip_column, color_term_significance, estimate_bv, regress_bv,
)


def synthetic(bv, nights=10, ct_b=0.1, ct_v=-0.04, mag_v=11.0):
    """A star of color `bv` measured in both bands on every night.

    The columns are built the way the pipeline stores them: `mag_color` is the
    true magnitude less the color of the star times the color term of its frame,
    which is what the correction has to undo. The color is what separates the
    two bands, so the B magnitude follows from the V one rather than being given.
    """
    mag_b = mag_v + bv

    mjds, filters, cts, mags, nn = [], [], [], [], []

    for night in range(nights):
        for band, ct, mag in (('B', ct_b, mag_b), ('V', ct_v, mag_v)):
            mjds.append(60000.0 + night + (0.0 if band == 'B' else 0.01))
            filters.append(band)
            cts.append(ct)
            mags.append(mag - bv*ct)
            nn.append('2023%04d' % night)

    n = len(mjds)

    return {
        'mjds': np.array(mjds), 'filters': np.array(filters),
        'color_term': np.array(cts), 'mag_color': np.array(mags),
        'sites': np.array(['auger']*n), 'ccds': np.array(['WF8']*n),
        'nights': np.array(nn, dtype=object),
    }


class TestColorAwareMags:
    def test_applies_the_color_term_of_every_frame(self):
        mags = color_aware_mags([12.0, 12.0], [0.1, -0.05], 0.8)

        assert mags == pytest.approx([12.08, 11.96])

    def test_a_missing_color_term_leaves_the_magnitude_alone(self):
        mags = color_aware_mags([12.0, 12.0], [np.nan, 0.1], 0.8)

        assert mags[0] == pytest.approx(12.0)
        assert mags[1] == pytest.approx(12.08)


class TestEstimateBv:
    @pytest.mark.parametrize('bv', [0.0, 0.35, 1.8, -0.2])
    def test_recovers_the_color_it_was_built_with(self, bv):
        data = synthetic(bv)
        idx = np.ones(len(data['mjds']), dtype=bool)

        value, npairs = estimate_bv(data, idx)

        # Exact, as the closed form inverts the very relation that built the data
        assert value == pytest.approx(bv)
        assert npairs == 10

    def test_the_correction_restores_the_true_magnitudes(self):
        data = synthetic(1.8)
        idx = np.ones(len(data['mjds']), dtype=bool)

        value, _ = estimate_bv(data, idx)
        mags = color_aware_mags(data['mag_color'], data['color_term'], value)

        assert mags[data['filters'] == 'B'] == pytest.approx(12.8)
        assert mags[data['filters'] == 'V'] == pytest.approx(11.0)

    def test_a_single_band_carries_no_color(self):
        data = synthetic(0.5)
        idx = data['filters'] == 'B'

        assert estimate_bv(data, idx) == (None, 0)

    def test_too_few_pairs_carry_no_color(self):
        data = synthetic(0.5, nights=BV_MIN_PAIRS - 1)
        idx = np.ones(len(data['mjds']), dtype=bool)

        assert estimate_bv(data, idx) == (None, 0)

    def test_the_bands_have_to_be_measured_together(self):
        # A B season and a V season, a year apart, make no pair at all
        data = synthetic(0.5)
        data['mjds'][data['filters'] == 'V'] += 365
        data['nights'][data['filters'] == 'V'] = '20240101'

        idx = np.ones(len(data['mjds']), dtype=bool)

        assert estimate_bv(data, idx) == (None, 0)

    def test_a_spoiled_frame_does_not_move_the_color(self):
        data = synthetic(0.5)
        data['mag_color'][0] += 5.0

        idx = np.ones(len(data['mjds']), dtype=bool)
        value, _ = estimate_bv(data, idx)

        assert value == pytest.approx(0.5)


class TestColorTermSignificance:
    """How much the color term varies against how well one frame measures it."""

    def constant(self, value, n=50):
        return np.full(n, float(value))

    def significance(self, spread, std, nstars, n=50):
        # A color term varying by `spread` about zero, measured on frames of the
        # given zero point scatter and calibration star count
        ct = np.linspace(-spread, spread, n)
        ct *= spread/np.std(ct)
        return color_term_significance(ct, self.constant(std, n),
                                       self.constant(nstars, n))

    def test_a_wide_field_carries_a_real_color_response(self):
        # 500 calibration stars pin the color term of a frame to about 0.003,
        # against the 0.03 it drifts over the archive
        assert self.significance(0.03, 0.045, 500) > COLOR_TERM_MIN_SIGNIFICANCE

    def test_a_narrow_field_carries_mostly_fit_noise(self):
        # 45 stars pin it no better than it appears to vary
        assert self.significance(0.04, 0.068, 45) < COLOR_TERM_MIN_SIGNIFICANCE

    def test_it_is_the_ratio_of_the_two(self):
        std, nstars = 0.05, 400
        sigma = std/(np.sqrt(nstars)*CAL_COLOR_SPREAD)

        assert self.significance(3*sigma, std, nstars) == pytest.approx(3.0, rel=1e-6)

    def test_too_few_points_to_judge(self):
        n = COLOR_TERM_MIN_POINTS - 1

        assert self.significance(0.03, 0.045, 500, n=n) == 0.0

    def test_a_constant_color_term_is_never_significant(self):
        # Not exactly zero, as the spread of a constant array is a rounding
        # error rather than nothing, but nowhere near being applied
        assert color_term_significance(self.constant(0.05), self.constant(0.045),
                                       self.constant(500)) < COLOR_TERM_MIN_SIGNIFICANCE

    def test_missing_frame_statistics_leave_it_unjudged(self):
        assert color_term_significance(np.linspace(-0.03, 0.03, 50),
                                       self.constant(np.nan),
                                       self.constant(np.nan)) == 0.0


@pytest.mark.django_db(databases=['fram', 'default'])
class TestQualityCutsPerCamera:
    """The cuts compare a camera against itself, not against another one."""

    # HD 7252, seen by both the narrow and the wide field camera of cta-n. Their
    # pixel scales and calibration depths have nothing in common, and the narrow
    # field takes an order of magnitude more measurements, so cutting the band as
    # a whole used to reject the wide field for not resembling it.
    POSITION = {'ra': 18.51521867, 'dec': 60.88311519, 'sr': 0.005}

    def kept(self, data, site, ccd, fname):
        return int(np.sum(data['idx0'] & (data['sites'] == site)
                          & (data['ccds'] == ccd) & (data['filters'] == fname)))

    @pytest.mark.parametrize('fname', ['R', 'V'])
    def test_the_wide_field_survives_beside_the_narrow_one(self, fname):
        data = build_lc(dict(self.POSITION))

        narrow = self.kept(data, 'cta-n', 'C0', fname)
        wide = self.kept(data, 'cta-n', 'WF0', fname)

        assert narrow > 1000

        # Roughly a third of them, as for every other camera and band here,
        # rather than the single measurement the pooled cut used to leave
        assert wide > 100


@pytest.mark.django_db(databases=['fram', 'default'])
class TestColorAwareLightCurve:
    # PY Gem, measured in every band by several cameras over the whole archive
    POSITION = {'ra': 96.01621596, 'dec': 25.41700394, 'sr': 0.005}

    def test_off_by_default(self):
        data = build_lc(dict(self.POSITION))

        assert data['color_aware'] is False
        assert data['color_applied'] is False
        assert data['bv'] is None

    def test_measures_the_color_and_applies_it(self):
        plain = build_lc(dict(self.POSITION))
        data = build_lc(dict(self.POSITION, color_aware='pairs'))

        assert data['color_applied'] is True
        assert data['bv_forced'] is False
        assert data['bv_pairs'] >= BV_MIN_PAIRS

        # A Be star, and so a blue one
        assert 0 < data['bv'] < 0.5

        assert len(data['mags']) == len(plain['mags'])
        assert not np.allclose(data['mags'], plain['mags'])

    def test_anything_but_fit_asks_for_the_measured_color(self):
        # One parameter says both whether to correct and where the color comes
        # from, so a value that only means "on" gets the default source
        data = build_lc(dict(self.POSITION, color_aware='on'))

        assert data['color_applied'] is True
        assert data['color_source'] == 'pairs'
        assert data['bv_source'] == 'pairs'

    def test_the_given_color_wins_over_the_measured_one(self):
        data = build_lc(dict(self.POSITION, color_aware='pairs', bv='0.14'))

        assert data['bv'] == pytest.approx(0.14)
        assert data['bv_forced'] is True

    def test_a_color_of_zero_is_a_color(self):
        data = build_lc(dict(self.POSITION, color_aware='pairs', bv='0'))

        assert data['bv'] == pytest.approx(0.0)
        assert data['bv_forced'] is True
        assert data['color_applied'] is True

    def test_an_unparseable_color_falls_back_to_the_measured_one(self):
        data = build_lc(dict(self.POSITION, color_aware='pairs', bv='blue'))

        assert data['bv_forced'] is False
        assert data['color_applied'] is True

    def test_a_single_band_falls_back_to_the_plain_magnitude(self):
        params = dict(self.POSITION, color_aware='pairs', filter='I')

        plain = build_lc(dict(params, color_aware=None))
        data = build_lc(params)

        # The request is remembered even though nothing came of it, so that the
        # caption can say why the curve is the default one
        assert data['color_aware'] is True
        assert data['color_applied'] is False
        assert data['bv'] is None

        assert np.allclose(data['mags'], plain['mags'], equal_nan=True)

    def test_a_given_color_still_obeys_the_significance_gate(self):
        # Forcing the color says nothing about how well the frames measure their
        # color term, which is what the gate is about, so the I band of this star
        # - seen by two cameras whose color term barely moves - is still declined
        params = dict(self.POSITION, color_aware='pairs', filter='I', bv='1.2')

        plain = build_lc(dict(params, color_aware=None, bv=None))
        data = build_lc(params)

        assert data['bv_forced'] is True
        assert data['color_applied'] is False
        assert data['color_groups'] == []
        assert all(_ < COLOR_TERM_MIN_SIGNIFICANCE
                   for _ in data['color_significance'].values())

        assert np.allclose(data['mags'], plain['mags'], equal_nan=True)

    def test_the_correction_tightens_the_b_band_curve(self):
        from astropy.stats import mad_std

        # Every band is fetched, as the color the correction needs is made of
        # the B and the V points together; only the B ones are then compared
        plain = build_lc(dict(self.POSITION))
        data = build_lc(dict(self.POSITION, color_aware='pairs'))

        assert data['color_applied'] is True

        # B carries the largest color terms of the archive, and they both drift
        # within a camera and differ between them, so the correction shows there
        for site, ccd in (('auger', 'WF8'), ('cta-n', 'WF0')):
            assert '%s/%s/B' % (site, ccd) in data['color_groups']

            def scatter(lc):
                idx = (lc['idx0'] & (lc['filters'] == 'B')
                       & (lc['sites'] == site) & (lc['ccds'] == ccd))
                return mad_std(np.asarray(lc['mags'], dtype=float)[idx])

            assert scatter(data) < scatter(plain)

    def test_the_correction_flattens_the_color_term_dependence(self):
        plain = build_lc(dict(self.POSITION))
        data = build_lc(dict(self.POSITION, color_aware='pairs'))

        for group in data['color_groups']:
            site, ccd, fname = group.split('/')

            def slope(lc):
                idx = (lc['idx0'] & (lc['filters'] == fname)
                       & (lc['sites'] == site) & (lc['ccds'] == ccd))
                ct = np.asarray(lc['color_term'], dtype=float)[idx]
                mag = np.asarray(lc['mags'], dtype=float)[idx]
                return np.polyfit(ct, mag - np.median(mag), 1)[0]

            # The whole point of the correction: what the plain magnitude of a
            # blue star gains from the color response of the frame, it takes
            # back out. The residual is what the color is uncertain by.
            assert abs(slope(data)) < abs(slope(plain))
            assert abs(slope(data)) < 0.35


@pytest.mark.django_db(databases=['fram', 'default'])
class TestPoorlyMeasuredColorTerm:
    """A camera that cannot measure its color term is left alone.

    The pipeline fits the zero point of a frame and its color term together, so
    where the calibration stars are few the two absorb each other's errors and
    `mag_color` is worse than the plain magnitude rather than better. cta-n/C0
    sees some fifty of them against the five hundred of a wide field.
    """

    # HD 7252 on the narrow field of cta-n
    POSITION = {'ra': 18.51521867, 'dec': 60.88311519, 'sr': 0.005,
                'site': 'cta-n', 'ccd': 'C0'}

    def test_the_correction_is_declined(self):
        data = build_lc(dict(self.POSITION, color_aware='pairs'))

        assert data['color_aware'] is True
        assert data['color_applied'] is False
        assert data['color_groups'] == []

        # No color is even looked for: which groups can take the correction is
        # settled first, and with none of them left there is nothing to measure
        # a color over - nor, for the fitted color, anything safe to fit to
        assert data['bv'] is None
        assert data['bv_source'] is None

        assert data['color_significance']
        assert all(_ < COLOR_TERM_MIN_SIGNIFICANCE
                   for _ in data['color_significance'].values())

    def test_the_magnitudes_are_left_as_they_are(self):
        plain = build_lc(dict(self.POSITION))
        data = build_lc(dict(self.POSITION, color_aware='pairs'))

        assert np.allclose(data['mags'], plain['mags'], equal_nan=True)


@pytest.mark.django_db(databases=['fram', 'default'])
class TestLightCurveJson:
    """What the plot in the browser is handed."""

    QUERY = 'ra=96.01621596&dec=25.41700394&sr=0.005'

    def get(self, client, extra=''):
        response = client.get('/photometry/json?' + self.QUERY + extra)

        assert response.status_code == 200

        return json.loads(response.content)

    # Every column the diagnostic view may put on the horizontal axis. A column
    # arriving as strings would silently turn the plot into a categorical one,
    # which is what `numpy.int64` not being a subclass of `int` used to do to
    # the two integer columns here.
    NUMERIC_COLUMNS = ['mags', 'magerrs', 'flags', 'fwhms', 'stds', 'nstars',
                       'color_term', 'mjds', 'xi', 'eta']

    @pytest.mark.parametrize('extra', ['', '&average=on'])
    def test_the_plotted_columns_are_numbers(self, client, extra):
        data = self.get(client, extra)

        assert data['lcs']

        for lc in data['lcs']:
            for column in self.NUMERIC_COLUMNS:
                assert lc[column], 'empty %s in %s' % (column, lc['filter'])
                assert all(isinstance(_, (int, float)) for _ in lc[column]), \
                    'non-numeric %s in %s' % (column, lc['filter'])

    def test_reports_the_color_it_applied(self, client):
        assert self.get(client)['color_aware'] is False
        assert self.get(client)['bv'] is None

        data = self.get(client, '&color_aware=pairs')

        assert data['color_aware'] is True
        assert 0 < data['bv'] < 0.5
        assert data['bv_pairs'] >= BV_MIN_PAIRS


def one_band(bv, n=60, cameras=('auger/WF8', 'cta-n/WF0'), mag=11.0, noise=0.0,
             ct_spread=0.05, seed=1):
    """A star measured in one band by a few cameras, each with its own zero point.

    `mag_color` is again what the pipeline stores - the true magnitude less the
    color of the star times the color term of the frame - so a fit to the color
    term has the star's color to find in it.
    """
    rng = np.random.default_rng(seed)

    ct, mags, groups = [], [], []

    for i, camera in enumerate(cameras):
        values = np.linspace(-ct_spread, ct_spread, n)
        ct.append(values)
        # A zero point of its own, an order of magnitude above what is sought
        mags.append(mag + 0.3*i - bv*values + rng.normal(0, noise, n))
        groups += [camera + '/B']*n

    return np.concatenate(mags), np.concatenate(ct), np.array(groups)


class TestRegressBv:
    """The color from the slope of the magnitude against the color term."""

    @pytest.mark.parametrize('bv', [0.0, 0.4, 1.7, -0.3])
    def test_recovers_the_color(self, bv):
        mags, ct, groups = one_band(bv)

        value, err, n = regress_bv(mags, ct, groups)

        assert value == pytest.approx(bv, abs=1e-6)
        assert n == len(mags)

    def test_the_zero_points_of_the_cameras_do_not_enter_it(self):
        # Two cameras half a magnitude apart, against a color signal of 0.02
        mags, ct, groups = one_band(0.4, cameras=('a/A', 'b/B', 'c/C'))

        assert regress_bv(mags, ct, groups)[0] == pytest.approx(0.4, abs=1e-6)

    def test_a_deviating_point_is_clipped(self):
        mags, ct, groups = one_band(0.4, noise=0.01)
        mags[3] += 5.0

        assert regress_bv(mags, ct, groups)[0] == pytest.approx(0.4, abs=0.05)

    def test_too_few_points_to_fit(self):
        mags, ct, groups = one_band(0.4, n=(BV_FIT_MIN_POINTS - 1)//2, cameras=('a/A',))

        assert regress_bv(mags, ct, groups) == (None, None, 0)

    def test_a_constant_color_term_has_no_slope_to_fit(self):
        mags, ct, groups = one_band(0.4)
        ct = np.zeros_like(ct)

        value, err, n = regress_bv(mags, ct, groups)

        # Degenerate with the zero points, so no color comes out of it
        assert value is None or not np.isfinite(err) or err > 1


@pytest.mark.django_db(databases=['fram', 'default'])
class TestFittedColorFallback:
    """The color fitted to the color term, for a star with one band only."""

    # PY Gem restricted to B, standing in for a star the archive never measured
    # in both bands
    POSITION = {'ra': 96.01621596, 'dec': 25.41700394, 'sr': 0.005, 'filter': 'B'}

    def test_pairs_have_nothing_to_work_with(self):
        data = build_lc(dict(self.POSITION, color_aware='pairs'))

        assert data['color_applied'] is False
        assert data['bv'] is None

    def test_the_fit_supplies_a_color(self):
        data = build_lc(dict(self.POSITION, color_aware='fit'))

        assert data['color_applied'] is True
        assert data['bv_source'] == 'fit'
        assert data['bv'] is not None
        assert data['bv_error'] is not None

        # Not the exactness of the two-band color - this star measures 0.072
        # there - but close enough to be worth applying
        assert abs(data['bv'] - 0.072) < 0.3

    def test_it_tightens_the_curve_much_as_the_measured_color_does(self):
        from astropy.stats import mad_std

        plain = build_lc(dict(self.POSITION))
        fitted = build_lc(dict(self.POSITION, color_aware='fit'))

        for group in fitted['color_groups']:
            site, ccd, fname = group.split('/')

            def scatter(lc):
                idx = (lc['idx0'] & (lc['sites'] == site) & (lc['ccds'] == ccd)
                       & (lc['filters'] == fname))
                return mad_std(np.asarray(lc['mags'], dtype=float)[idx])

            assert scatter(fitted) < scatter(plain)

    def test_a_given_color_still_wins(self):
        data = build_lc(dict(self.POSITION, color_aware='fit', bv='1.4'))

        assert data['bv'] == pytest.approx(1.4)
        assert data['bv_source'] == 'given'
        assert data['bv_forced'] is True


@pytest.mark.django_db(databases=['fram', 'default'])
class TestFittedColorIsNotAttemptedWhereItWouldLie:
    """The fit is only ever given the groups whose color term is worth applying.

    In a degenerate group `mag_color` varies as `-<B-V>_cal*ct` whatever the star
    does, so the fit would return the mean color of the calibration stars with a
    small formal error - a wrong answer that looks like a good one.
    """

    # HD 7252 on the narrow field of cta-n, where no group passes the gate
    POSITION = {'ra': 18.51521867, 'dec': 60.88311519, 'sr': 0.005,
                'site': 'cta-n', 'ccd': 'C0'}

    def test_no_color_is_fitted_at_all(self):
        plain = build_lc(dict(self.POSITION))
        data = build_lc(dict(self.POSITION, color_aware='fit'))

        assert data['color_groups'] == []
        assert data['bv'] is None
        assert data['bv_source'] is None
        assert data['color_applied'] is False

        assert np.allclose(data['mags'], plain['mags'], equal_nan=True)


class TestClipColumn:
    """The cut, and the population it takes its band from."""

    def population(self, n=100, spread=0.01, centre=0.05):
        values = np.linspace(centre - spread, centre + spread, n)
        return values

    def test_a_pair_cannot_be_cut_against_itself(self):
        # Whatever two measurements say, each is within any multiple of their
        # common deviation, so a group of two passes every cut it defines
        values = np.array([1.9, 1.87])
        idx = np.ones(2, dtype=bool)

        assert np.all(clip_column(idx, values, 'both'))

    def test_a_reference_population_rejects_them(self):
        values = np.concatenate([self.population(), [1.9, 1.87]])

        idx = np.zeros(len(values), dtype=bool)
        idx[-2:] = True

        reference = np.ones(len(values), dtype=bool)
        reference[-2:] = False

        assert not np.any(clip_column(idx, values, 'both', reference=reference))

    def test_the_reference_does_not_widen_the_selection(self):
        values = np.concatenate([self.population(), [0.05, 0.05]])

        idx = np.zeros(len(values), dtype=bool)
        idx[-2:] = True

        reference = np.ones(len(values), dtype=bool)

        # The two agree with the population, so they stay - and nothing else
        # joins them just because the band was derived from a wider set
        assert np.sum(clip_column(idx, values, 'both', reference=reference)) == 2

    def test_without_a_reference_it_cuts_against_itself(self):
        values = np.concatenate([self.population(), [1.9]])
        idx = np.ones(len(values), dtype=bool)

        kept = clip_column(idx, values, 'both')

        assert np.sum(kept) == len(values) - 1
        assert not kept[-1]

    def test_an_empty_reference_leaves_the_selection_alone(self):
        values = self.population()
        idx = np.ones(len(values), dtype=bool)

        assert np.all(clip_column(idx, values, 'both',
                                  reference=np.zeros(len(values), dtype=bool)))


@pytest.mark.django_db(databases=['fram', 'default'])
class TestSmallGroupsAreStillCut:
    """A camera and band with a handful of points is not a law unto itself."""

    # PY Gem at the radius the search form defaults to, where auger/WF4 took two
    # B frames whose color term is twenty times the usual and nothing else
    POSITION = {'ra': 96.01621596, 'dec': 25.41700394, 'sr': 3/3600}

    def test_no_absurd_color_term_reaches_the_curve(self):
        data = build_lc(dict(self.POSITION))

        color_term = np.asarray(data['color_term'], dtype=float)[data['idx0']]

        assert len(color_term)

        # The cameras of the archive sit within a couple of tenths of zero; the
        # pair that prompted this was at 1.9
        assert np.nanmax(np.abs(color_term)) < 0.3

    def test_the_small_groups_are_the_ones_being_judged(self):
        data = build_lc(dict(self.POSITION))

        groups = np.array(['%s/%s/%s' % (s, c, f) for s, c, f in
                           zip(data['sites'], data['ccds'], data['filters'])])

        # There are such groups here, so the test above is not vacuous
        sizes = [np.sum(data['idx0'] & (groups == g))
                 for g in set(groups[data['idx0']])]

        assert any(0 < _ < CLIP_MIN_POINTS for _ in sizes)
