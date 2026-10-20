// A writable tag sent to a device register (FC06) when its value changes, and again every RefreshMs so a
// device that restarted gets it back. Raw = (Value - tag Offset) / tag Scale, as a signed 16-bit register.
TYPE ST_BusWrite :
STRUCT
	TagIndex : INT;                     // 0 = unused row
	Line : INT;
	UnitId : UINT;
	Register : UINT;
	RefreshMs : UDINT := 10000;
END_STRUCT
END_TYPE
