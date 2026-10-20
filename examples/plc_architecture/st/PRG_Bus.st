PROGRAM PRG_Bus
// Bus task: fast cycle (about 5 ms), priority between PRG_Control and PRG_Comms. Owns every Modbus connection;
// the control task only sees GVL_Bus.Raw and the per-source health, through CollectBusInputs.
VAR
	Lines : ARRAY[1..GVL_Bus.LINE_COUNT] OF FB_BusLine;
	Reconnect : ARRAY[1..GVL_Bus.LINE_COUNT] OF BOOL;   // set online to reconnect a line with new settings
	Index : INT;
END_VAR
// ---- implementation ----
FOR Index := 1 TO GVL_Bus.LINE_COUNT DO
	Lines[Index](LineIndex := Index, Reconnect := Reconnect[Index]);
	Reconnect[Index] := FALSE;
END_FOR
