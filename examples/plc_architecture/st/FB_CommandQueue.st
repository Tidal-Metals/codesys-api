FUNCTION_BLOCK FB_CommandQueue
// Single-producer / single-consumer ring buffer between two tasks. Push is called from one task
// only, Pop from one other task only; each side writes only its own index, so no lock is needed. Push fills
// the slot before it advances Head, so Pop never sees a half-written item. This relies on both tasks running
// on one core; across cores, the index updates need the runtime's atomic operations and memory barriers.
// Usable capacity is SIZE - 1 (one slot stays empty to tell "full" from "empty").
VAR CONSTANT
	SIZE : UINT := 32;
END_VAR
VAR_OUTPUT
	OverflowCount : UDINT;              // items dropped because the queue was full
END_VAR
VAR
	Items : ARRAY[0..SIZE - 1] OF ST_Command;
	Head : UINT;                        // next free slot; written only by Push
	Tail : UINT;                        // next item to take; written only by Pop
END_VAR
// ---- implementation ----
// Everything happens in the Push and Pop methods.
