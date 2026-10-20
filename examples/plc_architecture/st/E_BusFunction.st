// Modbus read function of a poll block. Writes (FC06) come from GVL_Bus.Writes.
{attribute 'qualified_only'}
{attribute 'strict'}
TYPE E_BusFunction :
(
	READ_COILS := 1,
	READ_DISCRETE_INPUTS := 2,
	READ_HOLDING_REGISTERS := 3,
	READ_INPUT_REGISTERS := 4
) USINT;
END_TYPE
