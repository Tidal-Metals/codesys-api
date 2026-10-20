METHOD CallClient : BOOL
// Runs this line's client (TCP or serial) and returns IsConnected. Settings are read when it connects. A client
// error holds the connection down for a second before the next attempt.
VAR
	Port : SysCom.SYS_COM_PORTS;
	Baudrate : SysCom.SYS_COM_BAUDRATE;
	Parity : SysCom.SYS_COM_PARITY;
	Rts : SysCom.SYS_COM_RTS_CONTROL;
END_VAR
// ---- implementation ----
IF GVL_Bus.Lines[LineIndex].IsSerial THEN
	CASE GVL_Bus.Lines[LineIndex].ComPort OF
		2: Port := SysCom.SYS_COM_PORTS.SYS_COMPORT2;
		3: Port := SysCom.SYS_COM_PORTS.SYS_COMPORT3;
		4: Port := SysCom.SYS_COM_PORTS.SYS_COMPORT4;
	ELSE
		Port := SysCom.SYS_COM_PORTS.SYS_COMPORT1;
	END_CASE
	CASE GVL_Bus.Lines[LineIndex].RtsControl OF
		1: Rts := SysCom.SYS_COM_RTS_CONTROL.SYS_RTS_CONTROL_ENABLE;
		2: Rts := SysCom.SYS_COM_RTS_CONTROL.SYS_RTS_CONTROL_HANDSHAKE;
		3: Rts := SysCom.SYS_COM_RTS_CONTROL.SYS_RTS_CONTROL_TOGGLE;
	ELSE
		Rts := SysCom.SYS_COM_RTS_CONTROL.SYS_RTS_CONTROL_DISABLE;
	END_CASE
	CASE GVL_Bus.Lines[LineIndex].Baudrate OF
		19200: Baudrate := SysCom.SYS_COM_BAUDRATE.SYS_BR_19200;
		38400: Baudrate := SysCom.SYS_COM_BAUDRATE.SYS_BR_38400;
		57600: Baudrate := SysCom.SYS_COM_BAUDRATE.SYS_BR_57600;
		115200: Baudrate := SysCom.SYS_COM_BAUDRATE.SYS_BR_115200;
	ELSE
		Baudrate := SysCom.SYS_COM_BAUDRATE.SYS_BR_9600;
	END_CASE
	CASE GVL_Bus.Lines[LineIndex].Parity OF
		1: Parity := SysCom.SYS_COM_PARITY.SYS_ODDPARITY;
		2: Parity := SysCom.SYS_COM_PARITY.SYS_EVENPARITY;
	ELSE
		Parity := SysCom.SYS_COM_PARITY.SYS_NOPARITY;
	END_CASE
	Client REF= ClientRtu;
	ClientRtu(xConnect := IsEnabled AND NowMs >= HoldUntilMs, iPort := Port, dwBaudrate := Baudrate, eParity := Parity,
		eRTScontrol := Rts);
	IsConnected := ClientRtu.xConnected;
	IF ClientRtu.xError AND NowMs >= HoldUntilMs THEN
		HoldUntilMs := NowMs + 1000;
	END_IF
ELSE
	Client REF= ClientTcp;
	ClientTcp(xConnect := IsEnabled AND NowMs >= HoldUntilMs, aIPaddr := GVL_Bus.Lines[LineIndex].Address,
		uiPort := GVL_Bus.Lines[LineIndex].Port, tConnnectTimeOut := T#2S);
	IsConnected := ClientTcp.xConnected;
	IF ClientTcp.xError AND NowMs >= HoldUntilMs THEN
		HoldUntilMs := NowMs + 1000;
	END_IF
END_IF
CallClient := IsConnected;
