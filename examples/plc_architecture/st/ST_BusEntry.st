// Where one tag's raw value sits in its block's reply. Scaling is the tag's own (ST_TagConfig.Scale and
// Offset); the bus only delivers the device's number.
TYPE ST_BusEntry :
STRUCT
	Offset : UINT;                      // registers (or bits) from the block's Start
	Format : E_BusFormat;
	IsWordSwapped : BOOL;               // 32-bit values: low word first
	HasSentinel : BOOL;                 // a raw value the device uses for "no reading"
	Sentinel : DINT;                    // e.g. -999 for an open thermocouple; delivered as NaN, so the tag is INVALID
	TagIndex : INT;
END_STRUCT
END_TYPE
