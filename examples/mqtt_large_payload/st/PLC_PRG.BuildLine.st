// Action BuildLine: sets Line to payload line number Index (0-based), newline included.
// Value i is Sequence*1000 + i, or that divided by 100 as a two-decimal REAL.
// ---- implementation ----
IF Index = 0 THEN
	Line := CONCAT('DEMO_SEQ:', UDINT_TO_STRING(Sequence));
ELSIF Index = 1 THEN
	Line := CONCAT('DEMO_COUNT:', UINT_TO_STRING(ValueCount));
ELSIF Index = 2 THEN
	Line := SEL(IsRealFormat, 'DEMO_FORMAT:INT', 'DEMO_FORMAT:REAL');
ELSIF Index = ValueCount + 3 THEN
	Line := CONCAT('DEMO_END:', UDINT_TO_STRING(Sequence));
ELSE
	ValueIndex := Index - 2;
	Line := CONCAT(CONCAT('DEMO_V', UINT_TO_STRING(ValueIndex)), ':');
	IF IsRealFormat THEN
		RealValue := UDINT_TO_REAL(Sequence * 1000 + UINT_TO_UDINT(ValueIndex)) / 100.0;
		// The same rounding and conversion as BCNF's FB_InterlockMatrix.StringPublication.
		Line := CONCAT(Line, REAL_TO_STRING(DINT_TO_REAL(TRUNC(RealValue * 100.0 + SEL(RealValue >= 0.0, -0.5, 0.5))) / 100.0));
	ELSE
		Line := CONCAT(Line, UDINT_TO_STRING(Sequence * 1000 + UINT_TO_UDINT(ValueIndex)));
	END_IF
END_IF
Line := CONCAT(Line, '$N');
