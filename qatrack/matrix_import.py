"""
Matrix Dosimetry Results Import Module

This module imports Matrix dosimetry results from the MyQA database for QATrack.
It provides a modular and maintainable approach to retrieving and processing 
radiation measurement data across different linacs and energy modes.

Dependencies:
- Django settings
- pymssql for MS SQL database connections
"""

import json
from typing import Dict, Any, List, Optional
from django.conf import settings
import pymssql
from qatrack.qa.models import UnitTestInfo
from datetime import datetime, timedelta

# Constants
MYQA_DB_SETTINGS = {
	'server': settings.MYQA_DB_SERVER,
	'database': settings.MYQA_DB_NAME,
	'username': settings.MYQA_DB_USERNAME,
	'password': settings.MYQA_DB_PASSWORD
}

# Test Status Constants
class TestStatus:
	FAILED = "Failed"
	WARNING = "Warning"
	PASSED = "Passed"

class MatrixResultImporter:
	"""
	A comprehensive class for importing and processing Matrix dosimetry results
	"""
	
	def __init__(self, META):
		"""
		Initialize the importer with specific unit configuration
		
		:param unit_number: The unique identifier for the linac
		"""
		self.META = META
		self.unit_number = self.META["unit_number"]
		self.myqa_linac = self._map_unit_number_to_myqa_linac(self.unit_number)
		self.readings = self._initialize_readings()

	@staticmethod
	def _map_unit_number_to_myqa_linac(unit_number: int) -> str:
		"""
		Maps QATrack unit numbers to MyQA linac names
		
		:param unit_number: The unit number to map
		:return: Corresponding MyQA linac name
		"""
		linac_map = {
			4: "LA414 - H191733",
			3: "LA317 - H192972",
			1: "CST15 - H192361",
			2: "OBK15 - H192362",
			5: "LA512 - H191182",
			7: "LA524 - H196713",
			8: "LA224 - H196406",
			50: "DXR - GM0191",
		}
		return linac_map.get(unit_number, "none")

	@staticmethod
	def _initialize_readings() -> Dict[str, Optional[Any]]:
		"""
		Initialize a dictionary with default readings for various test configurations
		
		:return: Initialized readings dictionary
		"""
		readings = {}
		photon_energies = ["6x", "10x", "18x", "6fff", "10fff"]
		electron_energies = ["6e", "8e", "9e", "10e", "12e", "15e", "18e"]
		all_energies = photon_energies + electron_energies
		
		# Directional profile measurements (cl/il)
		directional_metrics = ["flat", "sym", "centre", "width", "lpen", "rpen"]
		for en in all_energies:
			for metric in directional_metrics:
				readings[f"mtx_{metric}_cl_{en}"] = None
				readings[f"mtx_{metric}_il_{en}"] = None
		
		# Photon-only inflection point measurements
		for en in photon_energies:
			readings[f"mtx_inflection_left_cl_{en}"] = None
			readings[f"mtx_inflection_left_il_{en}"] = None
			readings[f"mtx_inflection_right_cl_{en}"] = None
			readings[f"mtx_inflection_right_il_{en}"] = None
		
		# Electron-only flatness 80%/90% measurements
		for en in electron_energies:
			readings[f"mtx_flat_80_cl_{en}"] = None
			readings[f"mtx_flat_80_il_{en}"] = None
			readings[f"mtx_flat_90_cl_{en}"] = None
			readings[f"mtx_flat_90_il_{en}"] = None
		
		# Deviation (available on some linacs)
		for en in all_energies:
			readings[f"mtx_deviation_cl_{en}"] = None
			readings[f"mtx_deviation_il_{en}"] = None
		
		# Energy verification
		for en in all_energies:
			readings[f"mtx_energy_veri_{en}"] = None
		
		# Wedge constancy
		for en in ["6x", "10x", "18x"]:
			readings[f"mtx_wedge_cont_{en}"] = None
		
		readings.update({
			"mtx_taskid": None,
			"error": []
		})
		
		return readings

	def _get_database_connection(self):
		"""
		Establish a connection to the MyQA database
		
		:return: Database connection object
		"""
		try:
			return pymssql.connect(
				server=MYQA_DB_SETTINGS['server'], 
				database=MYQA_DB_SETTINGS['database'], 
				user=MYQA_DB_SETTINGS['username'], 
				password=MYQA_DB_SETTINGS['password']
			)
		except Exception as e:
			self.readings['error'].append(f"Database connection error: {str(e)}")
			print(e)
			raise

	def _execute_query(self, connection, query: str, params: tuple = ()) -> List[Dict]:
		"""
		Execute a SQL query and return results
		
		:param connection: Database connection
		:param query: SQL query to execute
		:param params: Optional query parameters
		:return: List of query results as dictionaries
		"""
		try:
			with connection.cursor(as_dict=True) as cursor:
				cursor.execute(query, params)
				return cursor.fetchall()
		except Exception as e:
			error_msg = f"Query execution error: {e}\nQuery: {query}"
			self.readings['error'].append(error_msg)
			raise RuntimeError(error_msg)

	def _process_profile_results(self, rows: List[Dict]) -> None:
		"""
		Process profile measurement results
		
		:param rows: Profile measurement rows from database
		"""
		for row in rows:
			try:
				# Determine measurement details (energy, direction, type)
				energy_type = self._get_energy_type(row)
				direction = self._get_profile_direction(row)
				measurement_type = self._get_measurement_type(row)
				
				# Construct test name
				test_name = f"mtx_{measurement_type}_{direction}_{energy_type}"
				
				# Set reading value
				self.readings[test_name] = round(row["Actual"], 2) if row["Actual"] is not None else None
			
			except Exception as e:
				self.readings['error'].append(f"Profile result processing error: {e}")

	def _process_energy_results(self, rows: List[Dict]) -> None:
		"""
		Process energy verification results
		
		:param rows: Energy verification rows from database
		"""
		for row in rows:
			# Generate energy type
			energy_type = self._get_energy_type(row)
			test_name = f"mtx_energy_veri_{energy_type}"
			
			# Determine test status
			status = self._determine_energy_test_status(row)
			
			# Update readings with appropriate status
			if status == TestStatus.FAILED:
				self.readings[test_name] = TestStatus.FAILED
			elif status == TestStatus.WARNING and self.readings[test_name] != TestStatus.FAILED:
				self.readings[test_name] = TestStatus.WARNING
			elif (status == TestStatus.PASSED and 
				  self.readings[test_name] not in [TestStatus.FAILED, TestStatus.WARNING]):
				self.readings[test_name] = TestStatus.PASSED

	def _process_wedge_results(self, rows: List[Dict]) -> None:
		"""
		Process wedge constancy results
		
		:param rows: Wedge constancy rows from database
		"""
		for row in rows:
			energy = str(int(row.get("Energy", 0)))
			wedge_key = f"mtx_wedge_cont_{energy}x"
			
			try:
				self.readings[wedge_key] = round(row["Actual"], 4) if row["Actual"] is not None else None
			except Exception as e:
				self.readings['error'].append(f"Wedge result processing error: {e}")

	@staticmethod
	def _get_energy_type(row: Dict) -> str:
		"""
		Determine energy type based on database row
		
		:param row: Database result row
		:return: Formatted energy type string
		"""
		energy_value = str(round(row.get("EnergyValue", row.get("Energy", 0))))
		
		mode = row.get("Description").lower()
		fff = row.get("IsFlatteningFilterFree")
		
		if mode == "electrons":
			return f"{energy_value}e"
		elif mode == "photons":
			return f"{energy_value}{'fff' if fff is True else 'x'}"
		
		return f"{energy_value}^^^unknown^^^"

	@staticmethod
	def _get_profile_direction(row: Dict) -> str:
		"""
		Determine profile direction
		
		:param row: Database result row
		:return: Profile direction ('il' or 'cl')
		"""
		return "il" if row.get("ProfileDirection", 0) == 1 else "cl"

	@staticmethod
	def _get_measurement_type(row: Dict) -> str:
		"""
		Map database display name to measurement type
		
		:param row: Database result row
		:return: Measurement type
		"""
		display_name_map = {
			"Flatness": "flat",
			"Symmetry": "sym",
			"Center": "centre",
			"Field Width": "width",
			"Penumbra Left": "lpen",
			"Penumbra Right": "rpen",
			"Inflection Point Left": "inflection_left",
			"Inflection Point Right": "inflection_right",
			"Flatness 80%": "flat_80",
			"Flatness 90%": "flat_90",
			"Deviation": "deviation"
		}
		return display_name_map.get(row.get("DisplayName", ""), row.get("DisplayName", "unknown"))

	@staticmethod
	def _determine_energy_test_status(row: Dict) -> Optional[str]:
		"""
		Determine test status based on actual and tolerance values
		
		:param row: Database result row
		:return: Test status (Passed/Warning/Failed)
		"""
		if row.get("Actual") is None:
			return None
		
		difference = abs(row["Actual"] - row["Expected"])
		
		if difference <= row.get("WarningTolerance", 0):
			return TestStatus.PASSED
		elif row.get("WarningTolerance", 0) < difference <= row.get("ErrorTolerance", 0):
			return TestStatus.WARNING
		elif row.get("ErrorTolerance", 0) < difference:
			return TestStatus.FAILED
		
		return None

	def import_results(self) -> str:
		"""
		Primary method to import Matrix results
		
		:param work_started: Timestamp of work start
		:return: JSON string of readings
		"""
		connection = None
		try:
			# Setup database connection and queries
			connection = self._get_database_connection()
			# Find the relevant task ID
			taskid_query = self._build_taskid_query()
			taskid_rows = self._execute_query(connection, taskid_query)
   
			if not taskid_rows:
				self.readings['error'].append(
				"No measurements matching the 'Work started' date/time. \n"
				"Change to correct date or set time later for historical lookups. \n"
				"If expected measurements not found check time of day is after the measurement. \n"
				)          
				return json.dumps({"error": self.readings['error']})
			
			taskid = taskid_rows[0].get("taskid")
			
			if not taskid:
				self.readings['error'].append(
				"Task ID is not found in query results"
				)          
				return json.dumps({"error": self.readings['error']})
			
			self.readings["mtx_taskid"] = str(taskid)

			if self._duplicate_entry(taskid):
				self.readings["error"].append(
				"Data for MatrixX task for this date/time already saved to QAtrack+"
				)
				return json.dumps({"error": self.readings['error']})


			# Execute different result queries
			profile_query = self._build_profile_query(taskid)
			energy_query = self._build_energy_query(taskid)
			wedge_query = self._build_wedge_query(taskid)

			profile_rows = self._execute_query(connection, profile_query)
			energy_rows = self._execute_query(connection, energy_query)
			wedge_rows = self._execute_query(connection, wedge_query)

			# Process results
			self._process_profile_results(profile_rows)
			self._process_energy_results(energy_rows)
			self._process_wedge_results(wedge_rows)
			
			if not self.readings['error']:
				del self.readings['error']
    
			return json.dumps(self.readings)
		
		except Exception as e:
			self.readings['error'].append(str(e))
			return json.dumps({"error": self.readings['error']})
		
		finally:
			if 'connection' in locals():
				connection.close()
				
	def _duplicate_entry(self, taskid):
		# Query previous tasklist instances with same taskid
		# Get testinstance id if testinstance found with same taskid
		# user_key ... https://docs.qatrackplus.com/en/stable/api/guide.html?highlight=duplicates#preventing-duplicate-entries-with-the-user-key-field
		try:
			instance = UnitTestInfo.objects.get(
				test__slug="mtx_taskid",
				unit__number=self.unit_number,
				testinstance__string_value=taskid,
			)
			return True
		except Exception as exception:
			return False
		
	def _build_taskid_query(self) -> str:
		"""
		Build SQL query to find the task ID
		
		:param work_started: Work start timestamp
		:return: SQL query string
		"""
		work_started = self.META["work_started"].replace(tzinfo=None)
		day_started = work_started.replace(minute=00, hour=00, second=00, microsecond=0)
		day_ended = work_started.replace(minute=59, hour=23, second=59, microsecond=0)
		
		if self.unit_number == 50:
			taskname_pattern = "5.Tmt.DXR.M%"
		else:
			taskname_pattern = "5.Tmt.Linac.M%Dosimetry%"
		
		return f"""
	Select top 1
		MQA_TestExecutions.TaskExecutionId as taskid,
		MQA_TestExecutions.FinishingDate,
		MQA_TestExecutions.RadiationDeviceName,
		MQA_TestExecutions.ProtocolName
	From
		MQA_TestExecutions
	Where
		MQA_TestExecutions.RadiationDeviceName = '{self.myqa_linac}' And
		MQA_TestExecutions.TaskName Like '{taskname_pattern}' AND
		MQA_TestExecutions.ReferenceDate BETWEEN '{day_started}' AND '{day_ended}'
	Order By
		MQA_TestExecutions.FinishingDate Desc
	"""

	def _build_profile_query(self, taskid: str) -> str:
		"""
		Build SQL query for profile measurements
		
		:param taskid: Task execution ID
		:return: SQL query string
		"""
		return f"""
			Select 
				MQA_TestExecutions.FinishingDate,
				MQA_Dosimetry_Profile_Results.Actual,
				MQA_Dosimetry_Profile_Results.Expected,
				MQA_Dosimetry_Profile_Results.DisplayName,
				MQA_Dosimetry_Profile_Results.ProfileDirection,
				MQA_TestExecutions.RadiationDeviceName,
				MQA_TestExecutions.ProtocolName,
				MQA_Dosimetry_Profile_TestExecutions.GantryAngle,
				MQA_TestExecutions.FinishingUser,
				DVC_RadiationDeviceEnergy.EnergyValue,
				DVC_EnergyType.Description,
				DVC_RadiationDeviceEnergy.IsFlatteningFilterFree,
				MQA_TaskExecutions.Id As TaskId
			From
				MQA_Dosimetry_Profile_Results Inner Join
				MQA_Dosimetry_Profile_QueueItemExecutions On MQA_Dosimetry_Profile_Results.ProfileQueueItemExecution_Id =
						MQA_Dosimetry_Profile_QueueItemExecutions.Id Inner Join
				MQA_Dosimetry_Profile_TestExecutions On MQA_Dosimetry_Profile_TestExecutions.ProfileQueueItem_Id =
						MQA_Dosimetry_Profile_QueueItemExecutions.Id Inner Join
				MQA_TestImplementationExecutions On MQA_Dosimetry_Profile_TestExecutions.Id = MQA_TestImplementationExecutions.Id
				Inner Join
				MQA_TestExecutions On MQA_TestImplementationExecutions.Id = MQA_TestExecutions.Id Inner Join
				MQA_TaskExecutions On MQA_TestExecutions.TaskExecutionId = MQA_TaskExecutions.Id Inner Join
				DVC_RadiationDeviceEnergy On
						DVC_RadiationDeviceEnergy.Id = MQA_Dosimetry_Profile_TestExecutions.BeamQuality_RadiationDeviceEnergyId
				Inner Join
				DVC_EnergyType On DVC_RadiationDeviceEnergy.EnergyTypeId = DVC_EnergyType.Id
			Where
				MQA_TestExecutions.TaskExecutionId = '{taskid}'
			Order By
				MQA_TestExecutions.FinishingDate Desc,
				MQA_Dosimetry_Profile_Results.DisplayName,
				MQA_Dosimetry_Profile_Results.ProfileDirection
			"""

	def _build_energy_query(self, taskid: str) -> str:
		"""
		Build SQL query for energy measurements
		
		:param taskid: Task execution ID
		:return: SQL query string
		"""
		return f"""
			Select
				TE.FinishingDate As TestFinished,
				TaskE.FinishingDate As TaskFinished,
				TE.RadiationDeviceName As Linac,
				CQIE.BeamQuality_EnergyValue As Energy,
				(Case CQIE.BeamQuality_EnergyDimension
					When '6'
					Then 'MeV'
					When '7'
					Then 'MV'
				End) As 'Mode',
				(Case
					When CQIE.BeamQuality_IsFlatteningFilterFree = 1
					Then 'FFF'
					Else ''
				End) As FFF,
				ECE.ChamberNumber As Chamber,
				ECE.Actual,
				ECE.Expected,
				TE.ProtocolName As Protocol,
				TE.FinishingUser As MeasuredBy,
				ETE.WarningTolerance,
				ETE.ErrorTolerance,
				TE.RadiationDeviceVendor As Manufacturer
			From
				MQA_Dosimetry_Energy_ChamberExecutions As ECE Inner Join
				MQA_Dosimetry_Energy_QueueItemExecutions As EQIE On ECE.EnergyConstancyQueueItemExecution_Id = EQIE.Id Inner Join
				MQA_Dosimetry_Energy_TestExecutions As ETE On EQIE.EnergyConstancyExecution_Id = ETE.Id Inner Join
				MQA_TestImplementationExecutions As TIE On ETE.Id = TIE.Id Inner Join
				MQA_TestExecutions As TE On TIE.Id = TE.Id Inner Join
				MQA_TaskExecutions As TaskE On TE.TaskExecutionId = TaskE.Id Inner Join
				MQA_Dosimetry_Common_QueueItemExecutions As CQIE On EQIE.Id = CQIE.Id
			Where
				TE.TaskExecutionId =  '{taskid}'
			Order By
				TestFinished Desc,
				CQIE.BeamQuality_EnergyDimension,
				Energy,
				Chamber
			"""

	def _build_wedge_query(self, taskid: str) -> str:
		"""
		Build SQL query for wedge measurements
		
		:param taskid: Task execution ID
		:return: SQL query string
		"""
		return f"""
			Select
				TaskE.FinishingDate As TaskFinished,
				TE.FinishingDate As TestFinished,
				TE.RadiationDeviceName As Linac,
				WTE.BeamQuality_EnergyValue as Energy,
				WQIE.ActualValue as Actual,
				WQIE.ExpectedValue as Expected,
				WQIE.Tolerance_Warn,
				WQIE.Tolerance_Fail,
				TE.ProtocolName As Protocol,
				TE.FinishingUser As MeasuredBy,
				TE.RadiationDeviceVendor As Manufacturer
			From
				MQA_TestImplementationExecutions As TIE Inner Join
				MQA_TestExecutions As TE On TIE.Id = TE.Id Inner Join
				MQA_TaskExecutions As TaskE On TE.TaskExecutionId = TaskE.Id Inner Join
				MQA_Dosimetry_Wedge_TestExecutions As WTE On WTE.Id = TIE.Id Inner Join
				MQA_Dosimetry_Wedge_QueueItemExecutions As WQIE On WQIE.WedgeConstancyExecution_Id = WTE.Id
			Where
				TE.TaskExecutionId =  '{taskid}'
			Order By
				TestFinished Desc
			"""

def import_matrix_results(META):
	"""
	Entry point function for QATrack composite test
	
	:param META: Metadata dictionary from QATrack
	:return: JSON string of Matrix results
	"""

	importer = MatrixResultImporter(META)
	return importer.import_results()

