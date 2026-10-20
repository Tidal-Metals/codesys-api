PROGRAM PRG_SerialProbe
// Receive-only check of a PLC serial port, no Modbus: opens the port with SysCom and counts every byte that
// arrives, keeping the last 32. For "the PLC sends but never hears a reply": send a known pattern from the PC
// (bench/serial_pattern.py) and see whether it lands here. Turn the bus line on that port off first
// (PRG_Bus.Lines[n].IsEnabled := FALSE); a port can only be open once. Called from the bus task.
VAR
	IsEnabled : BOOL;                   // set online
	ComPort : INT := 2;
	Baudrate : UDINT := 9600;
	IsVendorSequence : BOOL := TRUE;    // open like AutomationDirect's example (SysComOpen + SysComSetSettings)
	SetResult : UDINT;

	IsOpen : BOOL;
	OpenResult : UDINT;                 // runtime error code of the last open; 0 = OK
	BytesReceived : UDINT;
	ReadCalls : UDINT;
	LastBytes : ARRAY[0..31] OF BYTE;   // most recent bytes, oldest overwritten first
	NextSlot : INT;

	Handle : SysCom.RTS_IEC_HANDLE;
	Settings : SysCom.SysComSettings;
	Result : SysCom.RTS_IEC_RESULT;
	Buffer : ARRAY[0..63] OF BYTE;
	Count : UDINT;
	Index : UDINT;
END_VAR
// ---- implementation ----
IF IsEnabled AND NOT IsOpen THEN
	Settings.sPort := SysCom.SYS_COM_PORTS.SYS_COMPORT1;
	IF ComPort = 2 THEN
		Settings.sPort := SysCom.SYS_COM_PORTS.SYS_COMPORT2;
	END_IF
	Settings.ulBaudrate := SysCom.SYS_COM_BAUDRATE.SYS_BR_9600;
	IF Baudrate = 115200 THEN
		Settings.ulBaudrate := SysCom.SYS_COM_BAUDRATE.SYS_BR_115200;
	END_IF
	Settings.byParity := SysCom.SYS_COM_PARITY.SYS_NOPARITY;
	Settings.byStopBits := SysCom.SYS_COM_STOPBITS.SYS_ONESTOPBIT;
	Settings.ulTimeout := 0;
	Settings.ulBufferSize := 0;
	IF IsVendorSequence THEN
		// AutomationDirect's Demo_SerialPassthrough: open the port, then apply the settings.
		Settings.ulTimeout := 10;
		Handle := SysCom.SysComOpen(sPort := Settings.sPort, pResult := ADR(Result));
		OpenResult := Result;
		IF Result = 0 THEN
			Result := SysCom.SysComSetSettings(hCom := Handle, pSettings := ADR(Settings), pSettingsEx := 0);
			SetResult := Result;
		END_IF
	ELSE
		Handle := SysCom.SysComOpen2(pSettings := ADR(Settings), pSettingsEx := 0, pResult := ADR(Result));
		OpenResult := Result;
	END_IF
	IsOpen := Result = 0;
ELSIF NOT IsEnabled AND IsOpen THEN
	SysCom.SysComClose(hCom := Handle);
	IsOpen := FALSE;
END_IF

IF IsOpen THEN
	Count := SysCom.SysComRead(hCom := Handle, pbyBuffer := ADR(Buffer), ulSize := SIZEOF(Buffer), ulTimeout := 0, pResult := ADR(Result));
	ReadCalls := ReadCalls + 1;
	IF Count > 0 THEN
		FOR Index := 0 TO MIN(Count, SIZEOF(Buffer)) - 1 DO
			LastBytes[NextSlot] := Buffer[Index];
			NextSlot := (NextSlot + 1) MOD 32;
		END_FOR
		BytesReceived := BytesReceived + Count;
	END_IF
END_IF
