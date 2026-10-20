// One Modbus connection: a TCP server (a device or an RS485 gateway port) or one of the PLC's serial ports.
// Every device on it shares this one connection; requests on it run one at a time.
TYPE ST_BusLine :
STRUCT
	IsSerial : BOOL;
	Address : ARRAY[0..3] OF BYTE;      // TCP: server IP
	Port : UINT := 502;                 // TCP: server port
	ComPort : INT := 1;                 // serial: 1 to 4
	RtsControl : USINT;                 // serial: 0 disabled, 1 on, 2 handshake, 3 toggle (RS485 direction)
	Baudrate : UDINT := 9600;           // serial: 9600, 19200, 38400, 57600 or 115200
	Parity : USINT;                     // serial: 0 none, 1 odd, 2 even
	ReplyTimeoutMs : UDINT := 500;
END_STRUCT
END_TYPE
