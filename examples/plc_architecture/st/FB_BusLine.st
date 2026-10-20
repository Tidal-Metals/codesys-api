{attribute 'no_assign'}
FUNCTION_BLOCK FB_BusLine
// One Modbus connection (GVL_Bus.Lines[LineIndex]) with every block and write on it. Called every bus-task
// cycle. One request is in flight at a time; the next starts in the same call that finishes the last
// (ModbusFB's "daisy chain"), so the line never idles a task cycle between requests.
VAR_INPUT
	LineIndex : INT;
	IsEnabled : BOOL := TRUE;
	Reconnect : BOOL;                   // rising edge: drop the connection and connect with the current settings
END_VAR
VAR_OUTPUT
	IsConnected : BOOL;
	RequestCount : UDINT;
	ErrorCount : UDINT;
	LastRequestUs : UDINT;              // start to reply of the last request
	MaxRequestUs : UDINT;
END_VAR
VAR
	ClientTcp : ModbusFB.ClientTCP;
	ClientRtu : ModbusFB.ClientSerial;
	Client : REFERENCE TO ModbusFB.Client;   // whichever of the two this line uses (set by CallClient)
	ReadCoils : ModbusFB.ClientRequestReadCoils;
	ReadDiscrete : ModbusFB.ClientRequestReadDiscreteInputs;
	ReadHolding : ModbusFB.ClientRequestReadHoldingRegisters;
	ReadInput : ModbusFB.ClientRequestReadInputRegisters;
	WriteRegister : ModbusFB.ClientRequestWriteSingleRegister;
	Words : ARRAY[0..124] OF WORD;      // reply of the active register block
	Bits : ARRAY[0..1999] OF BYTE;      // reply of the active bit block: one byte per bit (ModbusFB unpacks them)
	Block : ST_BusBlock;                // copy of the active block
	ActiveBlock : INT;                  // 0 = no read in flight
	ActiveWrite : INT;                  // 0 = no write in flight
	NextBlock : INT := 1;               // round-robin start
	BlockDueMs : ARRAY[1..GVL_Bus.BLOCK_COUNT] OF ULINT;
	WriteDueMs : ARRAY[1..GVL_Bus.WRITE_COUNT] OF ULINT;
	WriteSentValue : ARRAY[1..GVL_Bus.WRITE_COUNT] OF REAL;
	HasWritten : ARRAY[1..GVL_Bus.WRITE_COUNT] OF BOOL;
	WriteValue : REAL;
	WriteRaw : INT;
	IsDone : BOOL;
	IsError : BOOL;
	ErrorId : UDINT;
	Exception : UDINT;
	NowMs : ULINT;
	StartUs : ULINT;
	ReconnectEdge : R_TRIG;
	HoldUntilMs : ULINT;                // connection held down until then (reconnect, client error)
END_VAR
// ---- implementation ----
NowMs := F_NowMs();
ReconnectEdge(CLK := Reconnect);
IF ReconnectEdge.Q THEN
	HoldUntilMs := NowMs + 500;
END_IF
CallClient();

IF ActiveBlock <> 0 OR ActiveWrite <> 0 THEN
	IF CallRequest(IsExecute := TRUE) THEN
		FinishRequest();
	END_IF
END_IF
IF ActiveBlock = 0 AND ActiveWrite = 0 AND IsConnected THEN
	StartNext();
END_IF
