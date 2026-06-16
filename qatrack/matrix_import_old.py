""" This module imports the Matrix dosimetry results from the MyQA database, for which connection details are stored 
in the local_settings.py file for the Django application.

This test is assigned to the Monthly Dosimetry using Matrix testlist, which are assigned to all linacs. 
The linac is determined from the assignment of the testlist to the linac.
Result from the database are collated into a dictionary which is returned as the value of the test.
The test's dictionary is then referenced by all the other tests in the teslist to populate all fields.

If there is any variation from the expected output this value should be manually validated. 

This module is called from a QATrack composite test of the same name (by convention).
The following header code should be placed in the composite test which reads this python file from the repository
then reloads it into the Django python environment without having to restart Django:
    import importlib
    # Substitute module name in following line (should correspond with this test's macro_name)
    check_mod = importlib.import_module(f".matrix_import", package="qat")
    importlib.reload(check_mod)
    # Substitute module name in following line
    reloaded_function = getattr(check_mod, "import_matrix_results")
Then the reloaded_function is called to assign a value to the composite test by its macro name:
    matrix_import = reloaded_function(META)

The imported Matrix values are added to a dictionary.
The dictionary is serialised as JSON and assigned to the output of the test.

To use this output in another composite test, e.g. mtx_flat_il_6x, in the same testlist one uses the following form:
    import json
    dict = json.loads(matrix_import)
    mtx_flat_il_6x = dict["mtx_flat_il_6x"]

Dependencies include:
- python module pymssql for the MS SQL connection. Install with other Django requirements via "pip install pymssql"

Written:
    7/3/2023 by G.Goozee 
"""
import django
django.setup()

from django.conf import settings
from datetime import datetime, timezone, date, time
from qatrack.qa.models import UnitTestInfo
import pymssql
import json

# Get DB connection information
SERVER = settings.MYQA_DB_SERVER
DB_NAME = settings.MYQA_DB_NAME
DB_USERNAME = settings.MYQA_DB_USERNAME
DB_PASSWORD = settings.MYQA_DB_PASSWORD

# MyQA test status options
FAILED = "Failed"
WARNING = "Warning"
PASSED = "Passed"


def duplicate_entry(taskid, unit):
    # Query previous tasklist instances with same taskid
    # Get testinstance id if testinstance found with same taskid
    # user_key ... https://docs.qatrackplus.com/en/stable/api/guide.html?highlight=duplicates#preventing-duplicate-entries-with-the-user-key-field
    try:
        instance = UnitTestInfo.objects.get(
            test__slug="mtx_taskid",
            unit__number=unit,
            testinstance__string_value=taskid,
        )
        return True
    except Exception as exception:
        return False


def import_matrix_results(META):
    params = ""
    msg = {}
    data_error = ""

    # Get runtime environment (i.e. test or prod) from variable configured in local_settings.py
    RUNTIME_ENV = settings.PHYS_REPO_SCRIPTS_PATH

    # Save results to dictionary
    readings = {}
    # Initialise values for each energy test
    for en in ["6x", '10x', "18x", '6fff', "10fff", "6e", "8e", "10e", "12e", "15e", "18e"]:
        # Energy verification where  en=6x, 18x, 10fff, 6e, 8e, 10e, 12e, 15e, 18e (maybe)
        readings[f"mtx_energy_veri_{en}"] = None
        readings[f"mtx_flat_cl_{en}"] = None
        readings[f"mtx_flat_il_{en}"] = None
        readings[f"mtx_sym_cl_{en}"] = None
        readings[f"mtx_sym_il_{en}"] = None
    readings["mtx_wedge_cont_6x"] = None
    readings["mtx_wedge_cont_18x"] = None

    unit_number = META["unit_number"]
    # Map unit # to MyQA unit names
    if unit_number == 1733:
        myqa_linac = "LA414 - H191733"
    elif unit_number == 6406:
        myqa_linac = "LA224 - H196406"
    else:
        linac = "none"
    testlistname = META["test_list_name"]
    # Remove timezone infor from work_started for datetime to use in SQL
    work_started = META["work_started"].replace(tzinfo=None)
    day_started = work_started.replace(minute=00, hour=00, second=00)
    day_ended = work_started.replace(minute=59, hour=23, second=59)

    # Get the taskid associated with the monthly, which is associated with profile, energy & wedge measurements
    # Finds the latest task prior to a given datetime and for a specific linac
    TASKID_QUERY = f"""
    Select top 1
        MQA_TestExecutions.TaskExecutionId as taskid,
        MQA_TestExecutions.FinishingDate,
        MQA_TestExecutions.RadiationDeviceName,
        MQA_TestExecutions.ProtocolName
    From
        MQA_TestExecutions
    Where
        MQA_TestExecutions.RadiationDeviceName = '{myqa_linac}' And
	MQA_TestExecutions.TaskName Like '5.Tmt.Linac.M.Dosimetry - Monthly QA' AND
        MQA_TestExecutions.ReferenceDate between '{day_started}' and '{day_ended}'
    Order By
        MQA_TestExecutions.ReferenceDate Desc
    """

    # Connect to DB, execute the SQL query and retrieve the rows
    # Get TaskID
    try:
        conn = pymssql.connect(
            host=SERVER, user=DB_USERNAME, password=DB_PASSWORD, database=DB_NAME
        )
        cursor = conn.cursor(as_dict=True)
        cursor.execute(TASKID_QUERY, params)
    except Exception as exception:
        msg[
            "error"
        ] = f"SQL query error. Exception: {exception}\n Query: {TASKID_QUERY}"
        return msg
    rows = cursor.fetchall()
    try:
        taskid = rows[0]["taskid"]
        readings["mtx_taskid"] = str(taskid)
    except Exception as exception:
        msg["error"] = (
            "No measurements matching the 'Work started' date/time. \n"
            "Change to correct date or set time later for historical lookups. \n"
            "If expected measurements not found check time of day is after the measurement. \n"
        )
        return msg

    # Check if results already in QATrack. Return error message
    duplicate = duplicate_entry(str(taskid), unit_number)
    if duplicate:
        msg[
            "error"
        ] = "Data for Matrix task for this date/time already saved to QATrack. Try adjusting 'Work started' date/time to just after the measurement."
        return msg

    PROFILE_QUERY = f"""
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

    ENERGY_QUERY = f"""
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

    WEDGE_QUERY = f"""
    Select
        TaskE.FinishingDate As TaskFinished,
        TE.FinishingDate As TestFinished,
        TE.RadiationDeviceName As Linac,
        WTE.BeamQuality_EnergyValue as Energy,
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

    # Set connection string to MyQA datasbase

    # Profile results
    try:
        cursor.execute(PROFILE_QUERY, taskid)
    except Exception as exception:
        msg[
            "error"
        ] = f"SQL profile query error. Exception: {exception}\n Query: {PROFILE_QUERY}"
        return msg
    rows = cursor.fetchall()

    # Assign flatness and symmetry (& other) results for inplane and crossplane for all energies
    for row in rows:
        energyvalue = round(row["EnergyValue"])
        if row["DisplayName"] == "Flatness":
            measurement_type = "flat"
        elif row["DisplayName"] == "Symmetry":
            measurement_type = "sym"
        elif row["DisplayName"] == "Center":
            measurement_type = "centre"
        elif row["DisplayName"] == "Field Width":
            measurement_type = "width"
        elif row["DisplayName"] == "Left Penumbra":
            measurement_type = "lpen"
        elif row["DisplayName"] == "Right Penumbra":
            measurement_type = "rpen"
        elif row["DisplayName"] == "Deviation":
            measurement_type = "deviation"
        else:
            # unexpected value in database:
            measurement_type = row["DisplayName"]
            data_error = f"{data_error} \nUnexpected profile type value: {measurement_type} for row: {row}"
        if row["Description"] == "Electrons":
            en = f"{energyvalue}e"
        elif row["Description"] == "Photons" and not row["IsFlatteningFilterFree"]:
            en = f"{energyvalue}x"
        elif row["Description"] == "Photons" and row["IsFlatteningFilterFree"]:
            en = f"{energyvalue}fff"
        else:
            # unexpected values in database
            en = f"{energyvalue}^^^{row['Description']}^^^"
            data_error = (
                f"{data_error} \nUnexpected profile energy value: {en} for row: {row}"
            )
        if row["ProfileDirection"] == 1:
            direction = "il"
        elif row["ProfileDirection"] == 2:
            direction = "cl"
        testname = f"mtx_{measurement_type}_{direction}_{en}"
        try:
            value = round(row["Actual"], 2)
            readings[testname] = value
        except Exception as exception:
            data_error = f"{data_error} \nActual energy value error in profile. Test may have been skipped. Row is {row}"
            readings[testname] = None

    # Energy results
    try:
        cursor.execute(ENERGY_QUERY, taskid)
    except Exception as exception:
        msg[
            "error"
        ] = f"SQL energy query error. Exception: {exception}\n Query: {ENERGY_QUERY}"
        return msg
    rows = cursor.fetchall()

    # Iterate over energies and chambers to generate testname and result status for each
    for row in rows:
        # Generate test name from row details
        energyvalue = round(row["Energy"])
        if row["Mode"] == "MeV":
            en = f"{energyvalue}e"
        elif row["Mode"] == "MV" and not row["FFF"] == "FFF":
            en = f"{energyvalue}x"
        elif row["Mode"] == "MV" and row["FFF"] == "FFF":
            en = f"{energyvalue}fff"
        else:
            # unexpected values in database
            en = f"{energyvalue}^^^{row['Mode']}^^^"
            data_error = (
                f"{data_error} \nUnexpected energy test value: {en} for row: {row}"
            )
        testname = f"mtx_energy_veri_{en}"

        # Get result status for given energy & chamber
        if row["Actual"] is not None:
            difference = abs(row["Actual"] - row["Expected"])
            if difference <= row["WarningTolerance"]:
                rowstatus = PASSED
            elif row["WarningTolerance"] < difference <= row["ErrorTolerance"]:
                rowstatus = WARNING
            elif row["ErrorTolerance"] < difference:
                rowstatus = FAILED
        else:
            rowstatus = None

        # Set status for given energy with highest warning/error status based on current and prior rows
        if rowstatus == FAILED:
            readings[testname] = FAILED
        elif rowstatus == WARNING and not readings[testname] == FAILED:
            readings[testname] = WARNING
        elif (
            rowstatus == PASSED
            and not readings[testname] == FAILED
            and not readings[testname] == WARNING
        ):
            readings[testname] = PASSED

    # Wedge results
    try:
        cursor.execute(WEDGE_QUERY, params)
    except Exception as exception:
        msg[
            "error"
        ] = f"SQL wedge query error. Exception: {exception}\n Query: {WEDGE_QUERY}"
        return msg
    rows = cursor.fetchall()

    # Close the cursor and the database connection
    cursor.close()
    conn.close()

    for row in rows:
        # Wedge constancy where  en=6x, 18x
        if int(row["Energy"]) == 18:
            try:
                readings["mtx_wedge_cont_18x"] = round(row["Actual"], 4)
            except Exception as exception:
                data_error = f"{data_error} \nActual wedge value error in profile. Test may have been skipped. Row is {row}"
                readings["mtx_wedge_cont_18x"] = None
        elif int(row["Energy"]) == 6:
            try:
                readings["mtx_wedge_cont_6x"] = round(row["Actual"], 4)
            except Exception as exception:
                data_error = f"{data_error} \nActual wedge value error in profile. Test may have been skipped. Row is {row}"
                readings["mtx_wedge_cont_6x"] = None
        else:
            data_error = f"{data_error} \nExpect energy value to be '6' or '18' but actually {row['Energy']}"
    if len(data_error) > 0:
        readings["error"] = data_error

    return json.dumps(readings)
