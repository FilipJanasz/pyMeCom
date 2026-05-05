from serial import Serial

# list of variables
vSP              = 0x00
vTI              = 0x01
vTR              = 0x02
vpP              = 0x03
vPow             = 0x04
vError           = 0x05
vWarn            = 0x06
vTE              = 0x07
vIntMove         = 0x08
vExtMove         = 0x09
vStatus1         = 0x0A
vBDPos           = 0x0B
vBDHeat          = 0x0C
vNiv             = 0x0F
vAutoPID         = 0x12
vTmpMode         = 0x13
vTmpActive       = 0x14
vCompAuto        = 0x15
vCircActive      = 0x16
vKeyLock         = 0x17
vCITM            = 0x18
vCETM            = 0x19
vICE             = 0x1A
vSNRL            = 0x1B
vSNRH            = 0x1C
vKpInt           = 0x1D
vTnInt           = 0x1E
vTvInt           = 0x1F
vKpJack          = 0x20
vTnJack          = 0x21
vTvJack          = 0x22
vKpProc          = 0x23
vTnProc          = 0x24
vTvProc          = 0x25
vnP              = 0x26
vTKwIn           = 0x2C
vpKw             = 0x2D
vPowCon          = 0x2E
vMinSP           = 0x30
vMaxSP           = 0x31
vNivHi           = 0x33
vNivLo           = 0x34
vNivCont         = 0x35
vTProc           = 0x3A
vStatus2         = 0x3C
vDistFeed        = 0x3D
vpPIn            = 0x3E
vBlDwn           = 0x3F
vWD1             = 0x40
vWD2             = 0x41
vSP2             = 0x42
vPMAMode         = 0x43
vPMA             = 0x44
vnPSet           = 0x48
vpPSet           = 0x49
vVPCMode         = 0x4A
vDesVPCPos       = 0x4B
vTKwOut          = 0x4C
vFluidFlow       = 0x4D
vFluidFlowSet    = 0x4E
vDeltaT          = 0x4F
vDeltaTAlarm     = 0x50
vTIAlarmHi       = 0x51
vTIAlarmLo       = 0x52
vTEAlarmHi       = 0x53
vTEAlarmLo       = 0x54
vOTHeater        = 0x55
vOTExpVessel     = 0x56
vProgramStart    = 0x58
vRampDuration    = 0x59
vRampStart       = 0x5A
vBlowDownPos     = 0x5B
vMaintenanceDays = 0x5C
vFGasDays        = 0x5D
vServicePackage  = 0x5E
vProgramState    = 0x5F
vpVPC            = 0x62
vTFlowMode       = 0x69
vTFlowVal        = 0x6A
vPumpCtrlMode    = 0x6B
vPoKoExtMode     = 0x6C
vPoKoState       = 0x6D
vPowHi           = 0x6E
vAirPurge        = 0x6F
vDrain           = 0x70
vSPT             = 0x71
vCurVPCPos       = 0x72
vMes             = 0x73
vDistFeedVPC     = 0x74
vCtrlPumpPresSrc = 0x75
vCtrlPumpPresVal = 0x76
vpPressurisation = 0x78
vOpTimePmp       = 0x79
vOpTimeCompr     = 0x7A
vOpTimeMachn     = 0x7B

PB_SIZE = 14 # extended accuracy PB command size

class InterfaceException(Exception):
	pass

class ResponseException(Exception):
	pass

class FormatException(Exception):
	pass

class Command:
	def __init__(self, addr, value=None):
		assert type(addr) is int
		assert type(value) is int or value is None
		self.addr = addr
		self.value = value
	
	def compose(self):
		addr = "{:02X}".format(self.addr)
		if self.value is not None:
			value = "{:08x}".format(self.value)
		else:
			value = "********"

		return "{{M{addr}{value}\r\n".format(addr=addr, value=value)

class Response:
	def __init__(self, addr, value=None):
		assert type(addr) is int
		assert type(value) is int or value is None
		self.addr = addr
		self.value = value

def decompose(command):
	assert type(command) is str

	try:
		prefix = command[0:2]
		addr = command[2:4]
		value = command[4:12]
		suffix = command[12:14]

		addr = int(addr, 16)
		if value != "********":
			value = int(value, 16)
		else:
			value = None
	except:
		raise FormatException

	if prefix != "{S" or suffix != "\r\n":
		raise FormatException

	return Response(addr, value)

def send(interface, command):
	assert type(interface) is Serial
	assert type(command) is Command
	interface.write(command.compose().encode("ascii"))
	interface.flush()

def recv(interface):
	assert type(interface) is Serial
	command = interface.read(PB_SIZE)
	if len(command) != PB_SIZE:
		error_description = "invalid response size: expected = {expected}, actual = {actual}".format(expected=PB_SIZE, actual=len(command))
		raise InterfaceException(error_description)

	try:
		decoded = command.decode("ascii")
	except UnicodeDecodeError as exc:
		raise FormatException from exc

	return decompose(decoded)

def read(interface, addr):
	assert type(interface) is Serial
	assert type(addr) is int
	send(interface, Command(addr))

	response = recv(interface)
	if response.addr != addr:
		raise ResponseException

	return response.value

def write(interface, addr, value):
	assert type(interface) is Serial
	assert type(addr) is int
	assert type(value) is int or value is None
	command = Command(addr, value)
	send(interface, command)

	response = recv(interface)
	if response.addr != addr or response.value != value:
		raise ResponseException
