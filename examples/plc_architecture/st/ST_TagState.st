// Live state of one tag. Written only by PRG_Control, each field by one step.
TYPE ST_TagState :
STRUCT
	Raw : REAL;                 // step 1: as read from the I/O or the bus
	SourceQuality : E_Quality;  // step 1: from the source's health and age
	Value : REAL;               // step 3 (step 2 for writable tags); BOOL tags use 0.0 / 1.0
	Quality : E_Quality;        // step 3: SourceQuality plus range checks (step 2 for writable tags)
	UpdatedAtMs : ULINT;        // step 1 (step 2 for writable tags): last fresh value, monotonic ms
	LastCommandSentAtMs : ULINT; // step 2: sender time of the last command applied, for ordering
END_STRUCT
END_TYPE
