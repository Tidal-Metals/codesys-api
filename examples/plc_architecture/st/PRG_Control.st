PROGRAM PRG_Control
// Control task: high priority, fixed interval (e.g. 50 ms). Runs the same pipeline every scan. Each step
// writes only its own results and reads only what the steps before it produced, so the order is the design.
VAR CONSTANT
	MAX_COMMANDS_PER_SCAN : INT := 10;  // bound the command work per scan; the rest waits in the queue
	MAX_COMMAND_AGE_MS : ULINT := 10000;
	MAX_FUTURE_SKEW_MS : ULINT := 2000; // a command dated further ahead than this is rejected
	MAX_QUEUE_AGE_MS : ULINT := 2000;   // ... and so is one that waited longer than this in the queue
	MIN_PLAUSIBLE_WALL_CLOCK_MS : ULINT := 1700000000000;  // before 2023-11: the RTC is not synchronized
	LEDGER_SIZE : INT := 64;            // answered commands remembered for retries; see ApplyCommands
	ALARM_HYSTERESIS : REAL := 0.1;
END_VAR
VAR
	NowAtMs : ULINT;                    // monotonic, for ages
	WallClockAtMs : ULINT;              // real-time clock, for command timestamps
	IsStarted : BOOL;
	Index : INT;
	Slot : INT;
	Command : ST_Command;

	// Command bookkeeping (ApplyCommands, CheckCommand)
	Ledger : ARRAY[0..LEDGER_SIZE - 1] OF ST_Command;
	NextLedgerSlot : INT;
	IsRetry : BOOL;

	// Alarms (EvaluateAlarms)
	AIT_1508_HH : BOOL;
	LSS_E_STOP_ACTIVE : BOOL;

	// Permissives (EvaluatePermissives)
	P_1502_Permit : BOOL;
	IsBypassActive : BOOL;
	P_1502_TrippedAtMs : ULINT;         // wall clock, last scan without the permit (ApplyCommands)
	BypassUntilMs : ULINT;              // a remote bypass expires; 0 = none (command path not in the skeleton)
	LocalBypassEnable : BOOL;           // key switch input: a remote bypass only works with it on

	// Diagnostics
	CommandsAccepted : UDINT;
	CommandsRejected : UDINT;
	RetriesAnswered : UDINT;
	AcksDropped : UDINT;
	LedgerTooSmall : UDINT;
END_VAR
// ---- implementation ----
NowAtMs := F_NowMs();
WallClockAtMs := F_WallClockMs();

ReadInputs();          // 1. I/O and bus values -> Tags[].Raw; quality from source health and age
ApplyCommands();       // 2. queued remote commands -> validated setpoints and requests, acknowledged
ComputeValues();       // 3. scaling, range checks, derived values
EvaluateAlarms();      // 4. alarm bits from values, quality and setpoints
EvaluatePermissives(); // 5. interlocks: what is allowed to run
WriteOutputs();        // 6. output := request AND permit; the only place outputs are written
ServeSnapshot();       // 7. a consistent copy of Tags for the comms task, when it asks
