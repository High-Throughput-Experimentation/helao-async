# helao.servers.visualizer package

## Submodules

## helao.servers.visualizer.action_visualizer module

### helao.servers.visualizer.action_visualizer.makeBokehApp(doc, confPrefix, server_key, helao_repo_root)

## helao.servers.visualizer.biologic_vis module

### *class* helao.servers.visualizer.biologic_vis.C_biovis(vis_serv, serv_key)

Bases: `object`

potentiostat visualizer module class

#### *async* IOloop_data()

#### \_\_init_\_(vis_serv, serv_key)

#### add_points(datapackage_list)

#### callback_input_max_points(attr, old, new, sender)

callback for input_max_points

#### callback_selector_change(attr, old, new)

#### cleanup_session(session_context)

#### reset_plot(channel, new_action_uuid=None, forceupdate=False)

#### update_input_value(sender, value)

## helao.servers.visualizer.co2_vis module

### *class* helao.servers.visualizer.co2_vis.C_co2(vis_serv, serv_key)

Bases: `object`

CO2 sensor visualizer module class

#### *async* IOloop_data()

#### \_\_init_\_(vis_serv, serv_key)

#### add_points(datapackage_list)

#### callback_input_max_points(attr, old, new, sender)

callback for input_max_points

#### callback_input_update_rate(attr, old, new, sender)

callback for input_update_rate

#### cleanup_session(session_context)

#### reset_plot(forceupdate=False)

#### update_input_value(sender, value)

## helao.servers.visualizer.gamry_vis module

### *class* helao.servers.visualizer.gamry_vis.C_potvis(vis_serv, serv_key)

Bases: `object`

potentiostat visualizer module class

#### *async* IOloop_data()

#### \_\_init_\_(vis_serv, serv_key)

#### add_points(datapackage_list)

#### callback_input_max_points(attr, old, new, sender)

callback for input_max_points

#### callback_input_max_prev(attr, old, new, sender)

callback for input_max_prev

#### callback_selector_change(attr, old, new)

#### callback_stop_measure(event)

#### cleanup_session(session_context)

#### reset_plot(new_action_uuid=None, forceupdate=False)

#### update_input_value(sender, value)

## helao.servers.visualizer.gpsim_live_vis module

### *class* helao.servers.visualizer.gpsim_live_vis.C_gpsimlivevis(vis_serv, serv_key)

Bases: `object`

GP simulator visualizer module class

#### *async* IOloop_data()

#### \_\_init_\_(vis_serv, serv_key)

#### add_points(datapackage_list)

#### callback_input_update_rate(attr, old, new, sender)

callback for input_update_rate

#### cleanup_session(session_context)

#### update_input_value(sender, value)

## helao.servers.visualizer.live_visualizer module

### helao.servers.visualizer.live_visualizer.makeBokehApp(doc, confPrefix, server_key, helao_repo_root)

## helao.servers.visualizer.mfc_vis module

### *class* helao.servers.visualizer.mfc_vis.C_mfc(vis_serv, serv_key)

Bases: `object`

mass flow controller visualizer module class

#### *async* IOloop_data()

#### \_\_init_\_(vis_serv, serv_key)

#### add_points(datapackage_list)

#### callback_input_max_points(attr, old, new, sender)

callback for input_max_points

#### callback_input_update_rate(attr, old, new, sender)

callback for input_update_rate

#### cleanup_session(session_context)

#### reset_plot(forceupdate=False)

#### update_input_value(sender, value)

## helao.servers.visualizer.nidaqmx_vis module

### *class* helao.servers.visualizer.nidaqmx_vis.C_nidaqmxvis(vis_serv, serv_key)

Bases: `object`

NImax visualizer module class

#### *async* IOloop_data()

#### \_\_init_\_(vis_serv, serv_key)

#### add_points(datapackage_list)

#### callback_input_max_points(attr, old, new, sender)

callback for input_max_points

#### cleanup_session(session_context)

#### reset_plot(new_action_uuid=None, forceupdate=False)

#### update_input_value(sender, value)

## helao.servers.visualizer.oersim_vis module

Action visualizer for the websocket simulator: WIP

### *class* helao.servers.visualizer.oersim_vis.C_oersimvis(vis_serv, serv_key)

Bases: `object`

spectrometer visualizer module class

#### *async* IOloop_data()

#### \_\_init_\_(vis_serv, serv_key)

#### add_points(datapackage_list)

#### callback_input_max_points(attr, old, new, sender)

callback for input_max_points

#### cleanup_session(session_context)

#### reset_plot(new_action_uuid=None, forceupdate=False)

#### update_input_value(sender, value)

## helao.servers.visualizer.pal_vis module

### *class* helao.servers.visualizer.pal_vis.C_palvis(vis_serv, serv_key)

Bases: `object`

PAL/archive visualizer module class

#### *async* IOloop_data()

#### \_\_init_\_(vis_serv, serv_key)

#### *async* add_points()

#### callback_inheritance(attr, old, new, sender)

callback for inheritance_select

#### callback_input_max_smps(attr, old, new, sender)

callback for input_max_smps

#### cleanup_session(session_context)

#### reset_plot()

#### update_inheritance_selector()

#### update_input_value(sender, value)

### helao.servers.visualizer.pal_vis.async_partial(f, \*args)

## helao.servers.visualizer.pressure_vis module

### *class* helao.servers.visualizer.pressure_vis.C_pressure(vis_serv, serv_key)

Bases: `object`

potentiostat visualizer module class

#### *async* IOloop_data()

#### \_\_init_\_(vis_serv, serv_key)

#### add_points(datapackage_list)

#### callback_input_max_points(attr, old, new, sender)

callback for input_max_points

#### callback_input_update_rate(attr, old, new, sender)

callback for input_update_rate

#### cleanup_session(session_context)

#### reset_plot(forceupdate=False)

#### update_input_value(sender, value)

## helao.servers.visualizer.spec_vis module

### *class* helao.servers.visualizer.spec_vis.C_specvis(vis_serv, serv_key)

Bases: `object`

spectrometer visualizer module class

#### *async* IOloop_data()

#### \_\_init_\_(vis_serv, serv_key)

#### add_points(datapackage_list)

#### callback_input_downsample(attr, old, new, sender)

callback for input_downsample

#### callback_input_max_spectra(attr, old, new, sender)

callback for input_max_spectra

#### cleanup_session(session_context)

#### reset_plot(new_action_uuid=None, forceupdate=False)

Clear current plot and move data to previous plot

#### update_input_value(sender, value)

## helao.servers.visualizer.syringe_vis module

Live visualizer for syringe pump server: WIP

### *class* helao.servers.visualizer.syringe_vis.C_syringe(vis_serv, serv_key)

Bases: `object`

syringe pump visualizer module class

#### *async* IOloop_data()

#### \_\_init_\_(vis_serv, serv_key)

#### add_points(datapackage_list)

#### callback_input_max_points(attr, old, new, sender)

callback for input_max_points

#### callback_input_update_rate(attr, old, new, sender)

callback for input_update_rate

#### cleanup_session(session_context)

#### reset_plot(forceupdate=False)

#### update_input_value(sender, value)

## helao.servers.visualizer.tec_vis module

### *class* helao.servers.visualizer.tec_vis.C_tec(vis_serv, serv_key)

Bases: `object`

TEC visualizer module class

#### *async* IOloop_data()

#### \_\_init_\_(vis_serv, serv_key)

#### add_points(datapackage_list)

#### callback_input_max_points(attr, old, new, sender)

callback for input_max_points

#### callback_input_update_rate(attr, old, new, sender)

callback for input_update_rate

#### cleanup_session(session_context)

#### reset_plot(forceupdate=False)

#### update_input_value(sender, value)

## helao.servers.visualizer.temp_vis module

### *class* helao.servers.visualizer.temp_vis.C_temperature(vis_serv, serv_key)

Bases: `object`

thermocouple visualizer module class

#### *async* IOloop_data()

#### \_\_init_\_(vis_serv, serv_key)

#### add_points(datapackage_list)

#### callback_input_max_points(attr, old, new, sender)

callback for input_max_points

#### callback_input_update_rate(attr, old, new, sender)

callback for input_update_rate

#### cleanup_session(session_context)

#### reset_plot(forceupdate=False)

#### update_input_value(sender, value)

## helao.servers.visualizer.wssim_live_vis module

### *class* helao.servers.visualizer.wssim_live_vis.C_simlivevis(vis_serv, serv_key)

Bases: `object`

potentiostat visualizer module class

#### *async* IOloop_data()

#### \_\_init_\_(vis_serv, serv_key)

#### add_points(datapackage_list)

#### callback_input_max_points(attr, old, new, sender)

callback for input_max_points

#### callback_input_update_rate(attr, old, new, sender)

callback for input_update_rate

#### cleanup_session(session_context)

#### update_input_value(sender, value)

## Module contents
