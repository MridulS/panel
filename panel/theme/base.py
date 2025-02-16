from __future__ import annotations

import functools
import os
import pathlib

from typing import (
    TYPE_CHECKING, Any, ClassVar, Dict, Tuple, Type,
)
from weakref import WeakKeyDictionary

import param

from bokeh.models import ImportedStyleSheet
from bokeh.themes import Theme as _BkTheme, _dark_minimal, built_in_themes

if TYPE_CHECKING:
    from bokeh.document import Document
    from bokeh.model import Model

    from ..viewable import Viewable


class Inherit:
    """
    Singleton object to declare stylesheet inheritance.
    """


class Theme(param.Parameterized):
    """
    Theme objects declare the styles to switch between different color
    modes. Each `Design` may declare any number of color themes.

    `_modifiers`
       The modifiers override parameter values of Panel components.
    """

    base_css = param.Filename(doc="""
        A stylesheet declaring the base variables that define the color
        scheme. By default this is inherited from a base class.""")

    bokeh_theme = param.ClassSelector(class_=(_BkTheme, str), default=None, doc="""
        A Bokeh Theme class that declares properties to apply to Bokeh
        models. This is necessary to ensure that plots and other canvas
        based components are styled appropriately.""")

    css = param.Filename(doc="""
       A stylesheet thats overrides variables specifically for the
       Theme subclass. In most cases this is not necessary.""")

    _modifiers: ClassVar[Dict[Viewable, Dict[str, Any]]] = {}


BOKEH_DARK = dict(_dark_minimal.json)
BOKEH_DARK['attrs']['Plot'].update({
    "background_fill_color": "#2b3035",
    "border_fill_color": "#212529",
})


class DefaultTheme(Theme):
    """
    Baseclass for default or light themes.
    """

    base_css = param.Filename(default=pathlib.Path(__file__).parent / 'css' / 'default.css')

    _name: ClassVar[str] = 'default'


class DarkTheme(Theme):
    """
    Baseclass for dark themes.
    """

    base_css = param.Filename(default=pathlib.Path(__file__).parent / 'css' / 'dark.css')

    bokeh_theme = param.ClassSelector(class_=(_BkTheme, str),
                                      default=_BkTheme(json=BOKEH_DARK))

    _name: ClassVar[str] = 'dark'


class Design(param.Parameterized):

    theme = param.ClassSelector(class_=Theme, constant=True)

    # Defines parameter overrides to apply to each model
    _modifiers: ClassVar[Dict[Viewable, Dict[str, Any]]] = {}

    # Defines the resources required to render this theme
    _resources: ClassVar[Dict[str, Dict[str, str]]] = {}

    # Declares valid themes for this Design
    _themes: ClassVar[Dict[str, Type[Theme]]] = {
        'default': DefaultTheme,
        'dark': DarkTheme
    }

    _caches: ClassVar[WeakKeyDictionary[Document, Dict[str, ImportedStyleSheet]]] = WeakKeyDictionary()

    def __init__(self, theme=None, **params):
        if isinstance(theme, type) and issubclass(theme, Theme):
            theme = theme._name
        elif theme is None:
            theme = 'default'
        theme = self._themes[theme]()
        super().__init__(theme=theme, **params)

    def _reapply(self, viewable: Viewable, root: Model, isolated: bool=True, cache=None) -> None:
        ref = root.ref['id']
        for o in viewable.select():
            if o.design and isolated:
                continue
            self._apply_modifiers(o, ref, self.theme, isolated, cache)

    def _apply_hooks(self, viewable: Viewable, root: Model) -> None:
        if root.document in self._caches:
            cache = self._caches[root.document]
        else:
            self._caches[root.document] = cache = {}
        with root.document.models.freeze():
            self._reapply(viewable, root, isolated=False, cache=cache)

    def _wrapper(self, viewable):
        return viewable

    @classmethod
    def _resolve_stylesheets(cls, value, defining_cls, inherited):
        new_value = []
        for v in value:
            if v is Inherit:
                new_value.extend(inherited)
            elif isinstance(v, str) and v.endswith('.css'):
                if v.startswith('http'):
                    url = v
                elif v.startswith('/'):
                    url = v[1:]
                else:
                    url = '/'.join(['bundled', cls.__name__.lower(), v])
                new_value.append(url)
            else:
                new_value.append(v)
        return new_value

    @classmethod
    @functools.lru_cache
    def _resolve_modifiers(cls, vtype, theme):
        """
        Iterate over the class hierarchy in reverse order and accumulate
        all modifiers that apply to the objects class and its super classes.
        """
        modifiers, child_modifiers = {}, {}
        for scls in vtype.__mro__[::-1]:
            cls_modifiers = cls._modifiers.get(scls, {})
            if cls_modifiers:
                # Find the Template class the options were first defined on
                def_cls = [
                    super_cls for super_cls in cls.__mro__[::-1]
                    if getattr(super_cls, '_modifiers', {}).get(scls) is cls_modifiers
                ][0]

                for prop, value in cls_modifiers.items():
                    if prop == 'children':
                        continue
                    elif prop == 'stylesheets':
                        modifiers[prop] = cls._resolve_stylesheets(value, def_cls, modifiers.get(prop, []))
                    else:
                        modifiers[prop] = value
            modifiers.update(theme._modifiers.get(scls, {}))
            child_modifiers.update(cls_modifiers.get('children', {}))
        return modifiers, child_modifiers

    @classmethod
    def _get_modifiers(
        cls, viewable: Viewable, theme: Theme = None, isolated: bool = True
    ):
        modifiers, child_modifiers = cls._resolve_modifiers(type(viewable), theme)
        modifiers = dict(modifiers)
        if 'stylesheets' in modifiers:
            if isolated:
                pre = list(cls._resources.get('css', {}).values())
                for p in ('base_css', 'css'):
                    css = getattr(theme, p)
                    if css is None:
                        continue
                    owner = type(theme).param[p].owner.__name__.lower()
                    if os.path.isfile(css):
                        css_file = '/'.join(['bundled', owner, os.path.basename(css)])
                        pre.append(css_file)
            else:
                pre = []
            modifiers['stylesheets'] = pre + modifiers['stylesheets']
        return modifiers, child_modifiers

    @classmethod
    def _patch_modifiers(cls, doc, modifiers, cache):
        if 'stylesheets' in modifiers:
            stylesheets = []
            for sts in modifiers['stylesheets']:
                if sts.endswith('.css'):
                    if cache and sts in cache:
                        sts = cache[sts]
                    else:
                        sts = ImportedStyleSheet(url=sts)
                        if cache is not None:
                            cache[sts.url] = sts
                stylesheets.append(sts)
            modifiers['stylesheets'] = stylesheets

    @classmethod
    def _apply_modifiers(cls, viewable: Viewable, mref: str, theme: Theme, isolated: bool, cache={}) -> None:
        if mref not in viewable._models:
            return
        model, _ = viewable._models[mref]
        modifiers, child_modifiers = cls._get_modifiers(viewable, theme, isolated)
        cls._patch_modifiers(model.document, modifiers, cache)
        if child_modifiers:
            for child in viewable:
                cls._apply_params(child, mref, child_modifiers)
        if modifiers:
            cls._apply_params(viewable, mref, modifiers)

    @classmethod
    def _apply_params(cls, viewable, mref, modifiers):
        from ..io.resources import CDN_DIST, patch_stylesheet

        model, _ = viewable._models[mref]
        params = {
            k: v for k, v in modifiers.items() if k != 'children' and
            getattr(viewable, k) == viewable.param[k].default
        }
        if 'stylesheets' in modifiers:
            params['stylesheets'] = modifiers['stylesheets'] + viewable.stylesheets
        props = viewable._process_param_change(params)
        doc = model.document
        if doc and 'dist_url' in doc._template_variables:
            dist_url = doc._template_variables['dist_url']
        else:
            dist_url = CDN_DIST
        for stylesheet in props.get('stylesheets', []):
            if isinstance(stylesheet, ImportedStyleSheet):
                patch_stylesheet(stylesheet, dist_url)
        model.update(**props)

    #----------------------------------------------------------------
    # Public API
    #----------------------------------------------------------------

    def apply(self, viewable: Viewable, root: Model, isolated: bool=True):
        """
        Applies the Design to a Viewable and all it children.

        Arguments
        ---------
        viewable: Viewable
            The Viewable to apply the Design to.
        root: Model
            The root Bokeh model to apply the Design to.
        isolated: bool
            Whether the Design is applied to an individual component
            or embedded in a template that ensures the resources,
            such as CSS variable definitions and JS are already
            initialized.
        """
        doc = root.document
        if not doc:
            self._reapply(viewable, root, isolated=isolated)
            return

        if doc in self._caches:
            cache = self._caches[doc]
        else:
            self._caches[doc] = cache = {}
        with doc.models.freeze():
            self._reapply(viewable, root, isolated=isolated, cache=cache)
            if self.theme and self.theme.bokeh_theme and doc:
                doc.theme = self.theme.bokeh_theme

    def apply_bokeh_theme_to_model(self, model: Model, theme_override=None):
        """
        Applies the Bokeh theme associated with this Design system
        to a model.
        """
        theme = theme_override or self.theme.bokeh_theme
        if isinstance(theme, str):
            theme = built_in_themes.get(theme)
        if not theme:
            return
        for sm in model.references():
            theme.apply_to_model(sm)

    def params(
        self, viewable: Viewable, doc: Document | None = None
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Provides parameter values to apply the provided Viewable.

        Arguments
        ---------
        viewable: Viewable
            The Viewable to return modifiers for.
        doc: Document | None
            Document the Viewable will be rendered into. Useful
            for caching any stylesheets that are created.

        Returns
        -------
        modifiers: Dict[str, Any]
            Dictionary of parameter values to apply to the Viewable.
        child_modifiers: Dict[str, Any]
            Dictionary of parameter values to apply to the children
            of the Viewable.
        """
        if doc is None:
            cache = {}
        elif doc in self._caches:
            cache = self._caches[doc]
        else:
            self._caches[doc] = cache = {}
        modifiers, child_modifiers = self._get_modifiers(viewable, theme=self.theme)
        self._patch_modifiers(doc, modifiers, cache)
        modifiers['tags'] = ['fast']
        return modifiers, child_modifiers


THEMES = {
    'default': DefaultTheme,
    'dark': DarkTheme
}
