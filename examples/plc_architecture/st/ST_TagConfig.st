// Static description of one tag. Generated from the config sheet into GVL_Tags.TagConfig;
// the program never writes it.
TYPE ST_TagConfig :
STRUCT
	Name : STRING(24);          // tag key, exactly as the bridge layout spells it; sized by the generator from the longest name
	Kind : E_TagKind;
	Scale : REAL := 1.0;        // Value := Raw * Scale + Offset
	Offset : REAL;
	MinValue : REAL;            // a value outside [MinValue, MaxValue], or NaN, is INVALID
	MaxValue : REAL;
	DefaultValue : REAL;        // writable tags start here (alarm setpoints from the sheet; requests 0)
	Deadband : REAL;            // report-by-exception: publish when the value moved more than this
	StaleAfter : TIME := T#5S;  // no fresh value from the source for this long -> STALE
	IsWritable : BOOL;          // may a remote command change it (setpoints, start/stop requests)?
	Source : INT;               // communication source in GVL_Tags.SourceIsHealthy; 0 = local I/O
END_STRUCT
END_TYPE
