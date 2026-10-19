// Quality of a tag's value. Interlocks and publishing look at this, not just at the number.
{attribute 'qualified_only'}
{attribute 'strict'}
TYPE E_Quality :
(
	INIT := 0,          // no value since start-up
	GOOD := 1,
	STALE := 2,         // no fresh value from the source within StaleAfter
	COMM_FAIL := 3,     // the source reports a communication error
	INVALID := 4        // out of range, or not computable (e.g. division by zero)
) USINT;
END_TYPE
