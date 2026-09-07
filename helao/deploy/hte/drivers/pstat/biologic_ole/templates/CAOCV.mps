EC-LAB SETTING FILE

Number of linked techniques : 2

EC-LAB for windows v11.72 (software)
Internet server v29.04 (firmware)
Command interpretor v15.01 (firmware)

Filename : D:\installers\CA_OCV.mps

Device : SP-200
Electrode connection : standard
Potential control : Ewe
Ewe ctrl range : min = -10.00 V, max = 10.00 V
Ewe,I filtering : 50 kHz
Safety Limits :
	Do not start on E overload
Channel : Grounded
Electrode material : 
Initial state : 
Electrolyte : 
Comments : 
Cable : straight
Reference electrode : SCE Saturated Calomel Electrode (0.241 V)
Electrode surface area : 0.001 cm²
Characteristic mass : 0.001 g
Equivalent Weight : 0.000 g/eq.
Density : 0.000 g/cm3
Volume (V) : 0.001 cm³
Cycle Definition : Charge/Discharge alternance
Turn to OCV between techniques

Technique : 1
Chronoamperometry / Chronocoulometry
Ei (V)              0.350               
vs.                 Ref                 
ti (h:m:s)          0:00:10.0000        
Imax                pass                
unit Imax           mA                  
Imin                pass                
unit Imin           mA                  
dQM                 0.000               
unit dQM            mA.h                
record              <I>                 
dI                  5.000               
unit dI             µA                  
dQ                  0.000               
unit dQ             mA.h                
dt (s)              0.1000              
dta (s)             0.1000              
E range min (V)     -10.000             
E range max (V)     10.000              
I Range             Auto                
I Range min         Unset               
I Range max         Unset               
I Range init        Unset               
Bandwidth           8                   
goto Ns'            0                   
nc cycles           0                   

Technique : 2
Open Circuit Voltage
tR (h:m:s)          0:00:30.0000        
dER/dt (mV/h)       1.0                 
record              <Ewe>               
dER (mV)            0.00                
dtR (s)             0.5000              
E range min (V)     -10.000             
E range max (V)     10.000              
