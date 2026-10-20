// Modbus devices and their hand-over to the control task. Tables are generated from the config sheets'
// rs485Config (and Modbus TCP devices); PRG_Bus (bus task) is the only writer of everything below them.
// Example: AIT-1508 is holding register 40002 (item 1) of RTU unit 24 on the PLC's first serial port.
{attribute 'qualified_only'}
VAR_GLOBAL CONSTANT
	LINE_COUNT : INT := 1;
	BLOCK_COUNT : INT := 1;
	ENTRY_COUNT : INT := 1;
	WRITE_COUNT : INT := 1;
	FAIL_LIMIT : UINT := 3;             // consecutive failed requests before a device is COMM_FAIL
	BACKOFF_MS : UDINT := 5000;         // a failed device is polled this rarely, so it can't slow its line
END_VAR
VAR_GLOBAL
	// Generated; never written by the program.
	Lines : ARRAY[1..LINE_COUNT] OF ST_BusLine := [(IsSerial := TRUE, ComPort := 1, Baudrate := 9600)];
	Blocks : ARRAY[1..BLOCK_COUNT] OF ST_BusBlock := [
		(Line := 1, UnitId := 24, ReadFunction := E_BusFunction.READ_HOLDING_REGISTERS, Start := 1, Count := 1,
		 PeriodMs := 500, FirstEntry := 1, EntryCount := 1, Source := 1)];
	Entries : ARRAY[1..ENTRY_COUNT] OF ST_BusEntry := [(Offset := 0, Format := E_BusFormat.UINT16, TagIndex := 1)];
	Writes : ARRAY[1..WRITE_COUNT] OF ST_BusWrite;          // no device setpoints in this example
	IsBusSource : ARRAY[0..GVL_Tags.SOURCE_COUNT] OF BOOL := [FALSE, TRUE, FALSE];

	// Bus task -> control task. For a source with SourceWriting TRUE the control task was started while the
	// bus task was mid-update: it keeps last scan's values for that source. (Both tasks on one core: control
	// never runs while the bus task writes, except by preempting it.)
	Raw : ARRAY[1..GVL_Tags.TAG_COUNT] OF REAL;             // decoded device numbers, before tag scaling
	SourceWriting : ARRAY[0..GVL_Tags.SOURCE_COUNT] OF BOOL;
	SourceHealthy : ARRAY[0..GVL_Tags.SOURCE_COUNT] OF BOOL := [TRUE, TRUE, TRUE];   // until FAIL_LIMIT failures: INIT, not COMM_FAIL
	SourceLastGoodMs : ARRAY[0..GVL_Tags.SOURCE_COUNT] OF ULINT;   // F_NowMs of the last good reply

	// Diagnostics
	SourceFailCount : ARRAY[0..GVL_Tags.SOURCE_COUNT] OF UINT;
	BlockReads : ARRAY[1..BLOCK_COUNT] OF UDINT;
	BlockErrors : ARRAY[1..BLOCK_COUNT] OF UDINT;
	BlockLastError : ARRAY[1..BLOCK_COUNT] OF UDINT;        // ModbusFB.Error
	BlockLastException : ARRAY[1..BLOCK_COUNT] OF UDINT;    // Modbus exception code
	WriteCount : ARRAY[1..WRITE_COUNT] OF UDINT;
	WriteErrors : ARRAY[1..WRITE_COUNT] OF UDINT;
END_VAR
