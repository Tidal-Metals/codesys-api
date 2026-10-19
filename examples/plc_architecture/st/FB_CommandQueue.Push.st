METHOD Push : BOOL
VAR_INPUT
	Item : ST_Command;
END_VAR
VAR
	Next : UINT;
END_VAR
// ---- implementation ----
Next := (Head + 1) MOD SIZE;
IF Next = Tail THEN
	OverflowCount := OverflowCount + 1;
	Push := FALSE;
	RETURN;
END_IF
Items[Head] := Item;
Head := Next;                           // publish the item only once it is complete
Push := TRUE;
