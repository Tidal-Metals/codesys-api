// Outcome of a remote command, sent back to the sender in the acknowledgement. A retry of an id the PLC has
// already answered gets the original result again; it is never applied twice.
{attribute 'qualified_only'}
{attribute 'strict'}
TYPE E_CommandResult :
(
	PENDING := 0,           // parsed, not yet checked
	ACCEPTED := 1,
	MALFORMED := 2,         // not "<id>,<tag>=<number>,<sent_ms>", or a field too long
	UNKNOWN_TAG := 3,
	NOT_WRITABLE := 4,
	OUT_OF_RANGE := 5,      // outside the tag's range, not 0/1 for a BOOL, not whole for an INT, NaN
	TOO_OLD := 6,           // older than allowed, dated in the future, or waited too long in the queue
	OUT_OF_ORDER := 7,      // older than the last command applied to the same tag
	INTERLOCKED := 8,       // a start while not permitted, or sent before the permit came back
	CLOCK_NOT_SYNCED := 9   // the PLC's wall clock isn't plausible, so freshness can't be checked
) USINT;
END_TYPE
