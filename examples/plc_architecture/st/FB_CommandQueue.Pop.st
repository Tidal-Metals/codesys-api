METHOD Pop : BOOL
VAR_IN_OUT
	Item : ST_Command;
END_VAR
// ---- implementation ----
IF Tail = Head THEN
	Pop := FALSE;
	RETURN;
END_IF
Item := Items[Tail];
Tail := (Tail + 1) MOD SIZE;
Pop := TRUE;
