// One read request, repeated every PeriodMs: a run of registers or bits of one device. The generator merges a
// device's nearby channels into as few blocks as possible (at most 125 registers or 2,000 bits each).
TYPE ST_BusBlock :
STRUCT
	Line : INT;                         // index in GVL_Bus.Lines
	UnitId : UINT;
	ReadFunction : E_BusFunction;
	Start : UINT;                       // zero-based register or bit address (CODESYS numbering)
	Count : UINT;
	PeriodMs : UDINT := 1000;
	FirstEntry : INT;                   // GVL_Bus.Entries[FirstEntry .. FirstEntry + EntryCount - 1]
	EntryCount : INT;
	Source : INT;                       // the device's source in GVL_Tags (health and age)
END_STRUCT
END_TYPE
