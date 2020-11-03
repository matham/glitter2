from typing import Type, Optional, Dict, List, Any, Tuple, Union, Callable
from functools import partial
from bisect import insort_left
from os.path import exists, join

from kivy.factory import Factory
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.widget import Widget
from kivy.properties import DictProperty, ListProperty, StringProperty, \
    ObjectProperty, BooleanProperty
from kivy.clock import Clock
from kivy.app import App

from more_kivy_app.app import app_error

from glitter2.analysis import AnalysisFactory, FileDataAnalysis, \
    AnalysisChannel, AnalysisSpec, default_value
from glitter2.utils import fix_name


def _sort_dict(d: dict) -> List[tuple]:
    return list(sorted(d.items(), key=lambda x: x[0]))


class ExportStatsSelection(BoxLayout):

    template_filename: str = ''

    template_file: Optional[FileDataAnalysis] = None

    template_data_file: Optional[FileDataAnalysis] = None

    global_parameters: BoxLayout = None

    local_parameters: BoxLayout = None

    new_channels_widget: BoxLayout = None

    compute_methods_widget: BoxLayout = None

    new_channel_methods: Dict[str, List[str]] = DictProperty()

    compute_methods: Dict[str, List[str]] = DictProperty()

    methods_class: Dict[Tuple[str, str], Type[AnalysisChannel]] = {}

    _update_name_width_trigger = []

    src_event_channel_names: List[str] = []

    src_pos_channel_names: List[str] = []

    src_zone_channel_names: List[str] = []

    event_channel_names: List[str] = ListProperty()

    pos_channel_names: List[str] = ListProperty()

    zone_channel_names: List[str] = ListProperty()

    widgets_using_channel_name: Dict[
        str, List['SpinnerTextContextBehavior']] = {}

    def __init__(self, **kwargs):
        self.new_channel_methods = {'event': [], 'pos': [], 'zone': []}
        self.compute_methods = {'event': [], 'pos': [], 'zone': []}
        super().__init__(**kwargs)

        self.src_event_channel_names = []
        self.src_pos_channel_names = []
        self.src_zone_channel_names = []
        self.widgets_using_channel_name = {}

    def get_template_file_setter(self, callback):
        def inner(paths):
            callback(paths)
            if paths:
                self.set_template_file(paths[0])
        return inner

    @app_error
    def set_template_file(self, filename):
        self.template_filename = filename

        if self.template_file is not None:
            self.template_file.close_data_file()
            self.template_file = None

        if self.template_data_file is not None:
            self.template_data_file.close_data_file()
            self.template_data_file = None

        # reset all the places where we refer to any of the original channels
        src_names = set(
            self.src_event_channel_names + self.src_pos_channel_names +
            self.src_zone_channel_names)
        widgets_using_channel_name = self.widgets_using_channel_name
        for name, widgets in list(widgets_using_channel_name.items()):
            # only clear when it refers to a source channel, not a manually
            # created channel
            if name not in src_names:
                continue

            for widget in widgets:
                widget.spinner_item_reference_was_removed()
            del widgets_using_channel_name[name]

        if not filename:
            self.src_event_channel_names = []
            self.src_pos_channel_names = []
            self.src_zone_channel_names = []

            self.refresh_channel_names(-1)
            return

        try:
            template = self.template_file = FileDataAnalysis(filename=filename)
            template.open_data_file()
            template.load_file_metadata()

            self.src_event_channel_names = list(template.event_channels_data)
            self.src_pos_channel_names = list(template.pos_channels_data)
            self.src_zone_channel_names = list(template.zone_channels_shapes)
        except Exception:
            self.src_event_channel_names = []
            self.src_pos_channel_names = []
            self.src_zone_channel_names = []

            self.refresh_channel_names(-1)

            self.template_filename = ''
            if self.template_file is not None:
                self.template_file.close_data_file()
                self.template_file = None

            raise

        self.refresh_channel_names(-1)

    def show_analysis_options(self):
        triggers = self._update_name_width_trigger = []
        for container in [
                self.global_parameters, self.local_parameters,
                self.new_channels_widget, self.compute_methods_widget]:
            triggers.append(Clock.create_trigger(
                partial(self._update_name_width, container), 0))

        self._show_global_variables()
        self._show_local_variables()
        self.get_compute_options()

    def _update_name_width(self, container, *args):
        children = container.children
        max_width = max(
            widget.name_label.texture_size[0] for widget in children)

        for widget in children:
            widget.name_label.parent.width = max_width

    def _show_global_variables(self):
        container = self.global_parameters
        global_vars = AnalysisFactory.get_variables(local_vars=False)
        trigger = self._update_name_width_trigger[0]
        for name, (classes, doc, (var_type, _), special_type) in _sort_dict(
                global_vars):
            widget = VariableDocWithDefault(
                name=name, classes=classes, doc=doc, var_type=var_type,
                special_type=special_type
            )
            container.add_widget(widget)
            widget.name_label.fbind('texture_size', trigger)

        trigger()

    def _show_local_variables(self):
        container = self.local_parameters
        local_vars = AnalysisFactory.get_variables(global_vars=False)
        trigger = self._update_name_width_trigger[1]
        for name, (classes, doc, (var_type, _), special_type) in _sort_dict(
                local_vars):

            widget = VariableDocNoDefault(
                name=name, classes=classes, doc=doc, var_type=var_type,
                special_type=special_type
            )
            container.add_widget(widget)
            widget.name_label.fbind('texture_size', trigger)

        trigger()

    def get_compute_options(self):
        new_methods = {}
        methods_class = {}
        for channel_type in ('event', 'pos', 'zone'):
            items = AnalysisFactory.get_channel_creating_methods_from_type(
                channel_type)
            new_methods[channel_type] = list(sorted(items))

            methods_class.update({
                (channel_type, name): cls
                for name, (cls, _, _) in items.items()
            })
        self.new_channel_methods = new_methods

        compute_methods = {}
        for channel_type in ('event', 'pos', 'zone'):
            items = AnalysisFactory.get_compute_methods_from_type(channel_type)
            compute_methods[channel_type] = list(sorted(items))

            methods_class.update({
                (channel_type, name): cls
                for name, (cls, _, _) in items.items()
            })
        self.compute_methods = compute_methods

        self.methods_class = methods_class

    def add_new_channel_computation(self, channel_type, method_name):
        cls = self.methods_class[(channel_type, method_name)]
        doc, ret_type, create_type, variables = \
            AnalysisFactory.get_channel_creating_method_spec(cls, method_name)

        widget = ComputeNewChannelWidget(
            export_stats=self, channel_type=channel_type, method_class=cls,
            name=method_name, doc=doc, create_type=create_type,
            variables=variables)
        self.new_channels_widget.add_widget(widget)
        self.refresh_channel_names(len(self.new_channels_widget.children) - 1)

        trigger = self._update_name_width_trigger[2]
        widget.name_label.fbind('texture_size', trigger)
        trigger()

    def add_computation(self, channel_type, method_name):
        cls = self.methods_class[(channel_type, method_name)]
        doc, ret_type, variables = \
            AnalysisFactory.get_compute_method_spec(cls, method_name)

        widget = ComputeMethodWidget(
            export_stats=self, channel_type=channel_type, method_class=cls,
            name=method_name, doc=doc, ret_type=ret_type, variables=variables)
        self.compute_methods_widget.add_widget(widget)

        trigger = self._update_name_width_trigger[3]
        widget.name_label.fbind('texture_size', trigger)
        trigger()

    def delete_new_channel(self, widget: 'ComputeNewChannelWidget'):
        index = self.new_channels_widget.children[::-1].index(widget)

        self.new_channels_widget.remove_widget(widget)
        widget.delete_method()

        old_name = widget.new_channel_name
        if not old_name:
            return

        # if old name was empty it'd just be an empty list
        widgets_using_name = self.widgets_using_channel_name.pop(old_name, [])
        for user in widgets_using_name:
            user.spinner_item_reference_was_removed()

        self.refresh_channel_names(index)

    def delete_computation(self, widget: 'ComputeMethodWidget'):
        self.compute_methods_widget.remove_widget(widget)
        widget.delete_method()

    def update_new_channel_name(
            self, widget: 'ComputeNewChannelWidget', name: str
    ) -> str:
        old_name = widget.new_channel_name
        if old_name == name:
            return name

        if name:
            # make sure channel with name doesn't exist yet
            name = fix_name(
                name, self.event_channel_names, self.pos_channel_names,
                self.zone_channel_names)
        widget.new_channel_name = name

        # if old name was empty it'd just be an empty list
        widgets_using_name = self.widgets_using_channel_name.get(old_name, [])
        for user in widgets_using_name:
            if name:
                user.spinner_item_reference_was_renamed(name)
            else:
                user.spinner_item_reference_was_removed()

        if name:
            # there won't be widgets using the new name - we fixed it
            self.widgets_using_channel_name[name] = widgets_using_name
        if old_name:
            self.widgets_using_channel_name[old_name] = []

        index = self.new_channels_widget.children[::-1].index(widget)
        self.refresh_channel_names(index)

        return name

    def refresh_channel_names(self, index: int):
        widgets = self.new_channels_widget.children[::-1]

        if index >= 0:
            # always start from previous widget in case it was deleted
            index -= 1

        if index == -1 or not widgets:
            channels = {
                'event': self.src_event_channel_names,
                'pos': self.src_pos_channel_names,
                'zone': self.src_zone_channel_names
            }
            index = 0
        else:
            widget: Optional['ComputeWidgetBase'] = widgets[index]
            channels = {
                'event': widget.event_channel_names,
                'pos': widget.pos_channel_names,
                'zone': widget.zone_channel_names
            }

            if widget.new_channel_name:
                items = channels[widget.create_type] = list(
                    channels[widget.create_type])
                insort_left(items, widget.new_channel_name)
            index = widgets.index(widget) + 1

        for current_widget in widgets[index:]:
            for create_type, items in channels.items():
                setattr(current_widget, f'{create_type}_channel_names', items)

            create_type = current_widget.create_type
            if current_widget.new_channel_name:
                items = channels[create_type] = list(channels[create_type])
                insort_left(items, current_widget.new_channel_name)

        for create_type, items in channels.items():
            setattr(self, f'{create_type}_channel_names', items)

    def use_name_of_other_channel(self, widget, old_name: str, name: str):
        if old_name == name:
            return

        widgets_using_name = self.widgets_using_channel_name.get(old_name, [])
        if widget in widgets_using_name:
            widgets_using_name.remove(widget)

        if name:
            if name not in self.widgets_using_channel_name:
                self.widgets_using_channel_name[name] = []
            self.widgets_using_channel_name[name].append(widget)

    def get_analysis_spec(self) -> AnalysisSpec:
        spec = AnalysisSpec()

        # add default variables
        default_variable: VariableDocWithDefault
        for default_variable in self.global_parameters.children[::-1]:
            for cls in default_variable.classes:
                spec.add_arg_default(
                    cls, default_variable.name, default_variable.value)

        # add new channel methods
        new_channel: ComputeNewChannelWidget
        for new_channel in self.new_channels_widget.children[::-1]:
            if not new_channel.new_channel_name:
                raise ValueError(
                    'no name given for the new channel created by '
                    f'"{new_channel.name}"')
            if not new_channel.compute_channel:
                raise ValueError(
                    'no channel was selected for the new channel created by '
                    f'"{new_channel.name}"')

            variables = new_channel.get_variable_values()
            method = getattr(
                new_channel.method_class, f'compute_{new_channel.name}')
            spec.add_new_channel_computation(
                new_channel.compute_channel, new_channel.new_channel_name,
                method, **variables)

        # add computation methods
        computation: ComputeMethodWidget
        for computation in self.compute_methods_widget.children[::-1]:
            if not computation.compute_channels:
                raise ValueError(
                    'no channel(s) ware selected for the computation by '
                    f'"{computation.name}"')

            variables = computation.get_variable_values()
            method = getattr(
                computation.method_class, f'compute_{computation.name}')
            spec.add_computation(
                computation.compute_channels, method,
                compute_key=computation.export_key, **variables)

        return spec


class VariableDocBase(BoxLayout):

    name = ''

    classes = []

    doc = ''

    var_type = None

    special_type = ''

    is_global = False

    name_label: Label = None

    def __init__(
            self, name, classes, doc, var_type, special_type, **kwargs):
        self.name = name
        self.classes = classes
        self.doc = doc
        self.var_type = var_type
        self.special_type = special_type
        super().__init__(**kwargs)


class VariableDocWithDefault(VariableDocBase):

    value = None

    is_global = True

    def set_value(self, widget, value):
        self.value = value

    def add_variable_widget(self, container):
        widget = get_variable_widget(
            None, self.var_type, self.special_type, self.set_value,
            optional=True, default=True
        )
        if widget is not None:
            container.add_widget(widget)


class VariableDocNoDefault(VariableDocBase):
    pass


class ComputeWidgetBase(BoxLayout):

    channel_type = ''

    method_class = None

    name = ''

    doc = ''

    variables = []

    export_stats: ExportStatsSelection = None

    variables_container = None

    variables_values: Dict[str, Any] = {}

    is_variable_optional: Dict[str, bool] = {}

    def __init__(
            self, export_stats: ExportStatsSelection, channel_type,
            method_class, name, doc, variables, **kwargs):
        self.export_stats = export_stats
        self.channel_type = channel_type
        self.method_class = method_class
        self.name = name
        self.doc = doc
        self.variables = variables
        self.variables_values = {}
        self.is_variable_optional = {}

        super().__init__(**kwargs)

        self.show_variables()

    def get_variable_callback(self, name, widget, value):
        self.variables_values[name] = value

    @property
    def channel_names_context(self):
        return self

    def show_variables(self):
        container = self.variables_container
        variables_values = self.variables_values
        is_variable_optional = self.is_variable_optional

        for name, ((var_type, optional), special_arg) in \
                _sort_dict(self.variables):
            variables_values[name] = None
            is_variable_optional[name] = optional

            widget = get_variable_widget(
                self.channel_names_context, var_type, special_arg,
                partial(self.get_variable_callback, name), optional=optional,
                default=False)
            if widget is None:
                continue

            container.add_widget(
                Factory.MinSizeYFlatLabel(text=f'{name}:', bold=True))
            container.add_widget(widget)

    def get_variable_values(self) -> Dict[str, Any]:
        # right now, None mean not set. TODO: use default_value for that case
        variables_values = self.variables_values
        variables = self.variables
        values = {}
        for name, value in variables_values.items():
            if value is None:
                value = default_value

            (var_type, optional), special_arg = variables[name]
            if value is default_value and not optional:
                raise ValueError(
                    f'Argument "{name}" for method "{self.name}" for channel '
                    f'type "{self.channel_type}" requires a value but none '
                    f'was given')
            values[name] = value

        return values

    def delete_method(self):
        # remove_variables_tracking_channel_names
        variables = _sort_dict(self.variables)
        widgets = self.variables_container.children[::-1][1::2]
        for widget, (name, (_, special_arg)) in zip(widgets, variables):
            if isinstance(widget, SpinnerListFromContext):
                widget.remove_widget_refs()
            elif special_arg:
                assert isinstance(
                    widget, Factory.VariableContextSpinner), widget
                widget.remove_reference_to_spinner_item()


class ComputeNewChannelWidget(ComputeWidgetBase):

    event_channel_names: List[str] = ListProperty()
    """Channels available so far."""

    pos_channel_names: List[str] = ListProperty()

    zone_channel_names: List[str] = ListProperty()

    new_channel_name: str = ''

    compute_channel: Optional[str] = ''

    channel_selector: 'SpinnerTextContextBehavior' = None

    def __init__(self, create_type, **kwargs):
        self.create_type = create_type

        super().__init__(**kwargs)

    def delete_method(self):
        super().delete_method()

        if self.channel_selector is not None:
            self.channel_selector.remove_reference_to_spinner_item()


class ComputeMethodWidget(ComputeWidgetBase):

    export_key: str = ''

    compute_channels: Optional[List[str]] = []

    channel_selector: 'SpinnerListFromContext' = None

    def __init__(self, ret_type, **kwargs):
        self.ret_type = ret_type
        self.compute_channels = []

        super().__init__(**kwargs)

    @property
    def channel_names_context(self):
        return self.export_stats

    def delete_method(self):
        super().delete_method()

        if self.channel_selector is not None:
            self.channel_selector.remove_widget_refs()


# TODO: add common inheritance for all variables, global, local, etc
# TODO: add way to distinguish when variable is default vs None

def get_variable_widget(
        context, var_type, special_arg, callback, optional=True, default=True):
    def set_text_value(value):
        if not value:
            value = None
        elif var_type == float:
            value = float(value)
        elif var_type == int:
            value = int(value)
        callback(widget, value)

    kwargs = {}
    optional_text = '(optional) ' if optional else 'required '
    default_text = 'default ' if default else ''
    hint = optional_text + default_text + 'value'

    if special_arg:
        if default:
            # these don't have a default
            return None

        include_none_in_values = default or optional
        if var_type == str:
            widget = Factory.VariableContextSpinner(
                variable_context=context,
                variable_name=f'{special_arg}_channel_names',
                variable_value_callback=callback,
                include_none_in_values=include_none_in_values)
        elif var_type == List[str]:
            widget = SpinnerListFromContext(
                variable_context=context,
                variable_name=f'{special_arg}_channel_names',
                variable_value_callback=callback,
                include_none_in_values=include_none_in_values)
        else:
            assert False, (special_arg, var_type)
        return widget

    if var_type == float:
        cls = Factory.ExportVariableTextInput
        kwargs['input_filter'] = 'float'
        kwargs['hint_text'] = hint
        cb = set_text_value
    elif var_type == int:
        cls = Factory.ExportVariableTextInput
        kwargs['input_filter'] = 'int'
        kwargs['hint_text'] = hint
        cb = set_text_value
    elif var_type == str:
        cls = Factory.ExportVariableTextInput
        kwargs['input_filter'] = None
        kwargs['hint_text'] = hint
        cb = set_text_value
    else:
        return None

    widget = cls(**kwargs)
    widget.value_callback = cb
    return widget


class ValueCallbackBehavior:

    variable_value_callback: Optional[Callable] = None

    # TODO: Make default use default_value and differentiate None/default
    variable_value = ObjectProperty(None, allownone=True)

    def __init__(
            self, variable_value_callback: Optional[Callable] = None, **kwargs):
        self.variable_value_callback = variable_value_callback
        super().__init__(**kwargs)

        self.fbind('variable_value', self._track_variable_value)
        self._track_variable_value()

    def _track_variable_value(self, *args):
        if self.variable_value_callback is not None:
            self.variable_value_callback(self, self.variable_value)


class SpinnerTextCallbackBehavior(ValueCallbackBehavior):

    def _track_variable_value(self, *args):
        value = self.variable_value
        if value == '<none>' or not value:
            value = None

        if self.variable_value_callback is not None:
            self.variable_value_callback(self, value)


class SpinnerFromContextBehavior:
    """Must have a values property (not set here as subclass likely has it).
    """

    variable_context = None

    variable_name = ''

    include_none_in_values = False

    def __init__(
            self, variable_context=None, variable_name: str = '',
            include_none_in_values=False, **kwargs):
        self.variable_context = variable_context
        self.variable_name = variable_name
        self.include_none_in_values = include_none_in_values

        super().__init__(**kwargs)

        Clock.schedule_once(self.bind_variable_values_from_context)

    def bind_variable_values_from_context(self, *args):
        self.variable_context.fbind(
            self.variable_name, self._update_values_from_context)
        self._update_values_from_context()

    def _update_values_from_context(self, *args):
        values = getattr(self.variable_context, self.variable_name)
        if self.include_none_in_values:
            self.values = ['<none>'] + values
        else:
            self.values = values


class SpinnerTextContextBehavior:
    """Must have a text property.

    It only updates the text property.
    """

    export_stats: ExportStatsSelection = None

    last_text = ''

    def __init__(self, **kwargs):
        self.export_stats = App.get_running_app().export_stats
        super().__init__(**kwargs)

        # register it if it has a name already
        self.change_spinner_item_referenced()

    def spinner_item_reference_was_removed(self):
        self.last_text = '<none>'
        self.text = '<none>'

    def spinner_item_reference_was_renamed(self, new_name):
        self.last_text = new_name
        self.text = new_name

    def change_spinner_item_referenced(self):
        last_text = self.last_text if self.last_text != '<none>' else ''
        text = self.text if self.text != '<none>' else ''
        self.export_stats.use_name_of_other_channel(self, last_text, text)
        self.last_text = text

    def remove_reference_to_spinner_item(self):
        last_text = self.last_text if self.last_text != '<none>' else ''
        self.export_stats.use_name_of_other_channel(self, last_text, '')
        self.last_text = ''


class SpinnerChannelNameItem(SpinnerTextContextBehavior, BoxLayout):

    text = StringProperty('')

    bold = BooleanProperty(False)

    def spinner_item_reference_was_removed(self):
        super().spinner_item_reference_was_removed()
        self.parent.remove_widget(self)

    def remove_reference_to_spinner_item(self):
        super().remove_reference_to_spinner_item()
        self.parent.remove_widget(self)


class SpinnerListFromContext(
        SpinnerFromContextBehavior, ValueCallbackBehavior, BoxLayout):

    values: List[str] = ListProperty()

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.fbind('values', self.update_shown_values)

    def update_values_from_children(self):
        children = self.ids.channel_selectors.children[::-1]
        # todo: use default_value
        self.variable_value = [c.text for c in children] or None

        self.update_shown_values()

    def remove_widget_refs(self):
        self.ids.channel_selector.remove_reference_to_spinner_item()
        widget: SpinnerTextContextBehavior
        for widget in self.ids.channel_selectors.children:
            widget.remove_reference_to_spinner_item()

    def update_shown_values(self, *args):
        spinner = self.ids.channel_selector
        used_values = self.variable_value or []

        values = [v for v in self.values if v not in used_values]
        spinner.values = values

        if spinner.text == '<none>' or not values or values == ['<none>']:
            return
        if spinner.text not in used_values:
            return

        if values[0] == '<none>':
            spinner.text = values[1]
        else:
            spinner.text = values[0]


Factory.register('ValueCallbackBehavior', cls=ValueCallbackBehavior)
Factory.register(
    'SpinnerTextCallbackBehavior', cls=SpinnerTextCallbackBehavior)
Factory.register('SpinnerFromContextBehavior', cls=SpinnerFromContextBehavior)
Factory.register(
    'SpinnerTextContextBehavior',
    cls=SpinnerTextContextBehavior)
