// How an entry's raw value sits in a block's reply: one bit, or one or two 16-bit registers.
{attribute 'qualified_only'}
{attribute 'strict'}
TYPE E_BusFormat :
(
	SINGLE_BIT := 0,
	INT16 := 1,
	UINT16 := 2,
	INT32 := 3,
	UINT32 := 4,
	FLOAT32 := 5
) USINT;
END_TYPE
