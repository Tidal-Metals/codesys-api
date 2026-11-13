// Layout of CODESYS's RtsByteString (CmpX509Cert/CmpCrypto), for X509ParseCertificate's pCert.
TYPE TlsProbeByteString :
STRUCT
	ui32MaxLen : UDINT;
	ui32Len : UDINT;
	pByData : POINTER TO BYTE;
END_STRUCT
END_TYPE
