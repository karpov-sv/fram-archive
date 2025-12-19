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
        choices=[('all', 'All')],# + (_,_ for _ in ccds)],
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
                Column('filename' if mode == 'images' else 'maxdist', css_class='col-md'),
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

        if mode == 'cutouts':
            self.fields['sr_value'].initial = 10
            self.fields['sr_units'].initial = 'arcmin'
