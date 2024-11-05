# helao.layouts package

## Submodules

## helao.layouts.aligner module

### *class* helao.layouts.aligner.Aligner(vis_serv, motor)

Bases: `object`

#### *async* IOloop_aligner()

IOloop for updating web interface

#### IOloop_helper()

#### \_\_init_\_(vis_serv, motor)

#### align_1p(xyplate, xymotor)

One point alignment

#### align_3p(xyplate, xymotor)

Three point alignment

#### *async* align_calc()

Calculate Transformation Matrix from given points

#### align_test_point(test_list)

Test if point is valid for aligning procedure

#### align_uniquepts(x, y)

#### callback_calib_file_input(attr, old, new)

#### callback_changed_motorstep(attr, old, new, sender)

callback for motor_step input

#### cleanup_session(session_context)

#### clicked_addpoint(event)

Add new point to calibration point list and removing last point

#### clicked_button_marker_move(idx)

move motor to maker position

#### clicked_buttonsel(idx)

Selects the Marker by clicking on colored buttons

#### clicked_calc()

wrapper for async calc call

#### clicked_calib_del_pt(idx)

remove cal point

#### clicked_go_align()

start a new alignment procedure

#### clicked_motor_mousemove_check(new)

#### clicked_move_down()

#### clicked_move_downleft()

#### clicked_move_downright()

#### clicked_move_left()

#### clicked_move_right()

#### clicked_move_up()

#### clicked_move_upleft()

#### clicked_move_upright()

#### clicked_moveabs()

move motor to abs position

#### clicked_moverel()

move motor by relative amount

#### clicked_pmplot(event)

double click/tap on PM plot to add/move marker

#### clicked_pmplot_mousepan(event)

#### clicked_pmplot_mousewheel(event)

#### clicked_readmotorpos()

gets current motor position

#### clicked_reset()

resets aligner to initial params

#### clicked_skipstep()

Calculate Transformation Matrix from given points

#### clicked_submit()

submit final results back to aligner server

#### create_layout()

#### cutoffdigits(M, digits)

#### *async* finish_alignment(newTransfermatrix, errorcode)

sends finished alignment back to FastAPI server

#### *async* get_pm()

gets plate map

#### get_samples(X, Y)

get list of samples row number closest to xy

#### init_mapaligner()

resets all parameters

#### *async* motor_getxy()

gets current motor position from alignment server

#### *async* motor_move(mode, x, y)

moves the motor by submitting a request to aligner server

#### remove_allMarkerpoints()

Removes all Markers from plot

#### stop_align()

#### update_Markerdisplay(selMarker)

updates the Marker display elements

#### update_TranferMatrixdisplay()

#### update_calpointdisplay(ptid)

Updates the calibration point display

#### update_input_value(sender, value)

#### update_pm_plot()

plots the plate map

#### update_pm_plot_title(plateid)

#### update_status(updatestr, reset=0)

updates the web interface status field

#### xy_to_sample(xy, pmapxy)

get point from pmap closest to xy

## Module contents
