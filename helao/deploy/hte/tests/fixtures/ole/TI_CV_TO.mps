EC-LAB SETTING FILE

Number of linked techniques : 3

EC-LAB for windows v11.72 (software)
Internet server v29.04 (firmware)
Command interpretor v5.40 (firmware)

Filename : D:\installers\TI_CV_TO.mps

Device : SP-200
Electrode connection : standard
Potential control : Ewe
Ewe ctrl range : min = -2.50 V, max = 2.50 V
Ewe,I filtering : 50 kHz
Safety Limits :
	Do not start on E overload
Channel : Grounded
Electrode material : 
Initial state : 
Electrolyte : 
Comments : 
Cable : standard
Electrode surface area : 0.000 cm²
Characteristic mass : 0.001 g
Equivalent Weight : 0.000 g/eq.
Density : 0.000 g/cm3
Volume (V) : 0.001 cm³
Cycle Definition : Charge/Discharge alternance
Turn to OCV between techniques

Technique : 1
Trigger In
Trigger             Rising Edge         
Channel             -1                  

Technique : 2
Cyclic Voltammetry
Ei (V)              0.000               
vs.                 Eoc                 
dE/dt               20.000              
dE/dt unit          mV/s                
E1 (V)              1.000               
vs.                 Ref                 
Step percent        50                  
N                   10                  
E range min (V)     -2.500              
E range max (V)     2.500               
I Range             Auto                
I Range min         Unset               
I Range max         Unset               
I Range init        Unset               
Bandwidth           8                   
E2 (V)              -1.000              
vs.                 Ref                 
nc cycles           0                   
Reverse Scan        1                   
Ef (V)              0.000               
vs.                 Eoc                 

Technique : 3
Trigger Out
Trigger             Rising Edge         
td (h:m:s)          0:00:0.0010         
