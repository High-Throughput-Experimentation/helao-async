EC-LAB SETTING FILE

Number of linked techniques : 2

Filename : C:\EC-Lab\Data\synthetic_CA.mps

Device : SP-300
Ecell ctrl range : min = -10.00 V, max = 10.00 V
Safety Limits :
	Do not start on E overload

Technique : 1
Chronoamperometry / Chronocoulometry
Ns                  0                   1                   
Ei (V)              0.000               0.500               
vs.                 Eoc                 Eoc                 
ti (h:m:s)          00:00:10.0000       00:00:20.0000       
Imax                pass                pass                
unit Imax           mA                  mA                  
record              <I>                 <I>                 
dI                  10.000              10.000              
unit dI             mA                  mA                  
dta (s)             0.0100              0.0100              
E range min (V)     -10.000             
E range max (V)     10.000              
I Range             Auto                
Bandwidth           4                   
goto Ns'            0                   
nc cycles           0                   

Technique : 2
Open Circuit Voltage
tR (h:m:s)          00:00:10.0000       
dER/dt (mV/h)       0.0                 
record              Ewe                 
dER (mV)            10.00               
dtR (s)             0.1000              
E range min (V)     -10.000             
E range max (V)     10.000              
