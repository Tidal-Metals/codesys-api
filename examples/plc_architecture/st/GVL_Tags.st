// The tag table and the hand-over points between the control task and the comms task.
// Ownership: every variable below has exactly one writer, named in its comment.
// Changing the table (rows, order, sizes) needs a full download: queued commands and the publisher's
// history refer to rows by index, so an online change must not reinterpret them.
{attribute 'qualified_only'}
VAR_GLOBAL CONSTANT
	TAG_COUNT : INT := 4;               // generated from the config sheet
	SOURCE_COUNT : INT := 2;            // Modbus slaves and remote PLCs; 0 = local I/O
	// Indices for hand-written logic, generated with the table so names and indices stay in step
	TAG_AIT_1508 : INT := 1;
	TAG_AIT_1508_HH_SP : INT := 2;
	TAG_P_1502_REQUEST : INT := 3;
	TAG_LSS_E_STOP : INT := 4;
END_VAR
VAR_GLOBAL
	// Generated from the config sheet; never written by the program.
	TagConfig : ARRAY[1..TAG_COUNT] OF ST_TagConfig := [
		(Name := 'AIT-1508', Kind := E_TagKind.REAL_TAG, Scale := 0.01, MinValue := 0.0, MaxValue := 14.0,
		 Deadband := 0.05, StaleAfter := T#3S, Source := 1),
		(Name := 'AIT-1508_HH_SP', Kind := E_TagKind.REAL_TAG, MinValue := 0.0, MaxValue := 14.0,
		 DefaultValue := 12.5, IsWritable := TRUE),
		(Name := 'P-1502', Kind := E_TagKind.BOOL_TAG, MinValue := 0.0, MaxValue := 1.0, IsWritable := TRUE),
		(Name := 'LSS-E-STOP', Kind := E_TagKind.BOOL_TAG, MinValue := 0.0, MaxValue := 1.0, StaleAfter := T#3S, Source := 2)];

	Tags : ARRAY[1..TAG_COUNT] OF ST_TagState;               // writer: PRG_Control
	RawInputs : ARRAY[1..TAG_COUNT] OF REAL;                  // writer: I/O mapping (control task)
	// Source health and the time of each source's last sample. Writer: the source adapters, which run in the
	// control task (Modbus diagnostics are read there). Data from other tasks (e.g. remote PLCs over MQTT)
	// reaches them through a queue, never by writing these from another task. Not in the skeleton.
	SourceIsHealthy : ARRAY[0..SOURCE_COUNT] OF BOOL := [TRUE, FALSE, FALSE];
	SourceUpdatedAtMs : ARRAY[0..SOURCE_COUNT] OF ULINT;      // 0 = no sample since start-up

	// Control -> comms: a consistent copy of Tags, made when the comms task asks for one.
	PublishSnapshot : ARRAY[1..TAG_COUNT] OF ST_TagState;    // writer: PRG_Control
	SnapshotRequest : UDINT;                                  // writer: PRG_Comms (increments to ask)
	SnapshotSequence : UDINT;                                 // writer: PRG_Control (= SnapshotRequest when served)

	// Comms -> control and back. Each queue has one producer task and one consumer task.
	// Both tasks must run on the same core, or the queues need the target's atomics and barriers.
	Commands : FB_CommandQueue;         // Push: FB_CommandReceiver (comms task); Pop: PRG_Control
	Acks : FB_CommandQueue;             // Push: PRG_Control; Pop: PRG_Comms

	// Physical outputs, mapped to I/O.
	P_1502_RUN : BOOL;                  // writer: PRG_Control.WriteOutputs, nothing else
END_VAR
