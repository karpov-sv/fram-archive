from django import forms

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Field, Fieldset, Div, Row, Column, Submit, HTML
from crispy_forms.bootstrap import InlineField, PrependedText, InlineRadios

import json

from . import models


class ImagesSearchForm(forms.Form):
    coords = forms.CharField(
        required=False, label="Center",
        widget=forms.TextInput(attrs={'placeholder': 'Coordinates or object name'})
    )
    sr_value = forms.FloatField(min_value=0, required=False, label="Radius")
    sr_units = forms.ChoiceField(
        choices=[('deg','Degrees'), ('arcmin','Arcmin'), ('arcsec','Arcsec')],
        required=False, label="Units"
    )

    site = forms.ChoiceField(
        choices=[('all', 'All')],# + (_,_ for _ in sites)],
        required=False, label="Site"
    )

    ccd = forms.ChoiceField(
        choices=(
            [('all', 'All')]
            # Meta-groups first — shortcuts users reach for most. Membership
            # lives in the DB view, so we do not enumerate the covered ccds
            # here (the same name could belong to more than one group later).
            # Tokens are 'all_nf', 'all_wf', ..., in line with the plain 'all'.
            + [(token, 'All ' + token[len('all_'):].upper())
               for token in models.PHOTOMETRY_CCD_GROUPS]
        ),
        required=False, label="CCD"
    )

    serial = forms.ChoiceField(
        choices=[('all', 'All')],# + (_,_ for _ in serials)],
        required=False, label="Camera Serial"
    )

    filter = forms.ChoiceField(
        choices=[('all', 'All')],# + (_,_ for _ in filters)],
        required=False, label="Filter"
    )

    type = forms.ChoiceField(
        choices=[('all', 'All')],# + (_,_ for _ in types)],
        required=False, label="Image Type"
    )

    target = forms.IntegerField(min_value=0, required=False, label="Target ID")

    night1 = forms.CharField(
        required=False, label="Not before",
        widget=forms.TextInput(attrs={'placeholder': 'YYYYMMDD'})
    )
    night2 = forms.CharField(
        required=False, label="Not after",
        widget=forms.TextInput(attrs={'placeholder': 'YYYYMMDD'})
    )

    filename = forms.CharField(
        required=False, label="Filename",
        widget=forms.TextInput(attrs={'placeholder': 'Part of image filename'})
    )

    maxdist = forms.FloatField(
        min_value=0, required=False, label="Max distance, degrees",
        widget=forms.NumberInput(attrs={'placeholder': 'Maximal allowed distance from frame center'})
    )

    nofiltering = forms.BooleanField(required=False, label="Disable quality cuts")

    colors = forms.BooleanField(
        required=False, label="Compute colors",
        widget=forms.CheckboxInput(attrs={
            'title': 'Show the colors of the star below the light curve, made of the '
                     'measurements of two bands taken close in time on the same night',
        })
    )

    # Whether to use the magnitudes calibrated with a color term, and where the
    # color to apply it with comes from - one question rather than two, as the
    # second is meaningless without the first
    color_aware = forms.ChoiceField(
        choices=[
            ('', 'Off'),
            ('pairs', 'B and V pairs'),
            ('fit', 'Fit to color term'),
        ],
        required=False, label="Color-aware",
        widget=forms.Select(attrs={
            'title': 'Apply the color term of every frame with the color of the star. The B '
                     'and V pairs of the star measure that color exactly but need both bands; '
                     'fitting the magnitude against the color term needs one band only, and is '
                     'far less reliable - check the value it reports.',
        })
    )

    bv = forms.FloatField(
        required=False, label="B-V",
        widget=forms.NumberInput(attrs={
            'placeholder': 'Auto',
            'title': 'Color to apply the color term with, overriding the one the light curve '
                     'gives. Needed for a star observed in a single band.',
        })
    )

    sigma = forms.FloatField(
        min_value=0, required=False, label="Clip, sigma",
        widget=forms.NumberInput(attrs={
            'placeholder': 'Off',
            'title': 'Reject the measurements deviating from the median magnitude of their camera '
                     'and filter by more than this many sigma. Off by default, as it also removes '
                     'the deep minima of a genuine variable.',
        })
    )

    average = forms.BooleanField(
        required=False, label="Average close points",
        widget=forms.CheckboxInput(attrs={
            'title': 'Combine the measurements of a single visit, per site, camera and filter',
        })
    )

    average_window = forms.FloatField(
        min_value=0, required=False, label="Within, s", initial=600,
        widget=forms.NumberInput(attrs={
            'placeholder': '600',
            'title': 'Largest gap between the measurements to be averaged together, in seconds',
        })
    )

    average_mode = forms.ChoiceField(
        choices=[('mean', 'Weighted mean'), ('median', 'Median'), ('clipped', 'Clipped mean')],
        required=False, label="Combined as"
    )

    def __init__(self, *args, **kwargs):
        mode = kwargs.pop('mode')

        sites = kwargs.pop('sites')
        ccds = kwargs.pop('ccds')
        serials = kwargs.pop('serials')
        filters = kwargs.pop('filters')
        types = kwargs.pop('types')

        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        # self.helper.form_tag = False
        # self.helper.disable_csrf = True
        self.helper.field_template = 'crispy_field.html'
        self.helper.layout = Layout(
            Row(
                Column('coords', css_class='col-md'),
                Column('sr_value', css_class='col-md-2'),
                Column('sr_units', css_class='col-md-auto'),
                css_class='align-items-end',
            ),
            Row(
                Column('site', css_class='col-md'),
                Column('ccd', css_class='col-md'),
                Column('serial', css_class='col-md'),
                Column('filter', css_class='col-md'),
                Column('type', css_class='col-md') if mode == 'images' else None,
                Column('target', css_class='col-md'),
                css_class='align-items-end',
            ),
            Row(
                Column('night1', css_class='col-md-auto'),
                Column('night2', css_class='col-md-auto'),
                Column('filename', css_class='col-md') if mode == 'images' else None,
                Column('maxdist', css_class='col-md') if mode == 'cutouts' else None,
                Column('sigma', css_class='col-md-auto') if mode == 'photometry' else None,
                Column('nofiltering', css_class="col-md-auto mb-2") if mode == 'photometry' else None,
                css_class='align-items-end',
            ),
            Row(
                Column('colors', css_class="col-md-auto mb-2"),
                Column('color_aware', css_class='col-md'),
                Column('bv', css_class='col-md'),
                Column('average', css_class='col-md-auto mb-2'),
                Column('average_mode', css_class='col-md'),
                Column('average_window', css_class='col-md'),
                css_class='align-items-end',
            ) if mode == 'photometry' else None,
            Row(
                Column(
                    Submit('search', 'Search', css_class='btn-primary mb-1'),
                    css_class="col-md-auto"
                ),
                css_class='align-items-end',
            ),
        )

        if sites is not None:
            self.fields['site'].choices += [(_['site'],_['site']) for _ in sites]

        if ccds is not None:
            self.fields['ccd'].choices += [(_['ccd'],_['ccd']) for _ in ccds]

        if serials is not None:
            self.fields['serial'].choices += [(_['serial'],_['serial']) for _ in serials]

        if filters is not None:
            self.fields['filter'].choices += [(_['filter'],_['filter']) for _ in filters]

        if types is not None:
            self.fields['type'].choices += [(_['type'],_['type']) for _ in types]

        # Both cutouts and photometry are extracted around a given position, and
        # so are meaningless without one, unlike the generic image search
        if mode == 'cutouts':
            self.fields['coords'].required = True
            self.fields['sr_value'].initial = 10
            self.fields['sr_units'].initial = 'arcmin'
        elif mode == 'photometry':
            self.fields['coords'].required = True
            self.fields['sr_value'].initial = 3
            self.fields['sr_units'].initial = 'arcsec'
