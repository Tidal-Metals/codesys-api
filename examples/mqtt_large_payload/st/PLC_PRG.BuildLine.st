// Action BuildLine: sets Line to payload line number Index (0-based), newline included.
// ---- implementation ----
IF Index = 0 THEN
	Line := CONCAT('DEMO_SEQ:', UDINT_TO_STRING(Sequence));
ELSIF Index = 1 THEN
	Line := CONCAT('DEMO_COUNT:', UINT_TO_STRING(ValueCount));
ELSIF Index = ValueCount + 2 THEN
	Line := CONCAT('DEMO_END:', UDINT_TO_STRING(Sequence));
ELSE
	Line := CONCAT(CONCAT('DEMO_V', UINT_TO_STRING(Index - 1)), ':');
	Line := CONCAT(Line, UDINT_TO_STRING(Sequence * 1000 + UINT_TO_UDINT(Index - 1)));
END_IF
Line := CONCAT(Line, '$N');
