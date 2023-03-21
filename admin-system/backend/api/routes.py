import datetime
import time
import uuid

import flask
from flask import Response, jsonify, request, Blueprint

import constants
from api import helpers, models
from api.app import db

api = Blueprint("api", __name__)


###################################################################################
#                               Client API Routes                                 #
###################################################################################
@api.route("/api", methods=["GET"], strict_slashes=False)
def index():
    """Index route for the API"""
    return Response("Hello, world!", status=200)


@api.route("/api/signup", methods=["POST"], strict_slashes=False)
def signup():
    """
    Route for signing up a new user

    JSON body::

        {
            "email": "name@domain.com",
            "password": "secure_password",
            "motion_pattern": ["direction", "direction", "direction", ...],
            "auth_methods": {
                "password": boolean,
                "motion_pattern": boolean,
                "face_recognition": boolean,
            },
        }

    - ``auth_methods``: is a dictionary of the authentication methods the user wants to use.

    Note that the password and motion pattern fields are only required if the corresponding auth method is enabled.

    :return: A success message or an error message
    """
    # Validate that the request is JSON
    try:
        request_data = helpers.json_validate(request)
    except AssertionError as exception_message:
        return jsonify(msg='Error: {}. User not created.'.format(exception_message), success=0), 400

    # Create the user and return an error message if it fails
    try:
        helpers.create_user_from_dict(request_data)
        return jsonify(msg='User successfully created.', success=1), 200
    except AssertionError as exception_message:
        return jsonify(msg='Error: {}. User not created.'.format(exception_message), success=0), 400


@api.route("/api/login/email", methods=["POST"], strict_slashes=False)
def init():
    """
    Route for initializing a login session

    JSON body::

        {
            "data": "name@domain.com",
        }

    :return: The session ID for the login session
    """
    # Validate that the request is JSON
    try:
        request_data = helpers.json_validate(request)
    except AssertionError as exception_message:
        return jsonify(msg='Error: {}. Login not initialized.'.format(exception_message), success=0), 400

    # Get the user from the email and check if they exist
    email: str = request_data.get('data', None)
    user: models.User = helpers.get_user_from_email(email)

    if user is None:
        return jsonify(msg="Email not found, please try again.", success=0), 401

    # Create a login session and return the session ID
    try:
        session = helpers.create_login_session(user)
        next_stage = helpers.get_next_auth_stage(session)
        return jsonify(msg='Login sequence initialized.', session_id=session.session_id, next=next_stage,
                       success=1), 200
    except AssertionError as exception_message:
        return jsonify(msg='Error: {}. Login not initialized.'.format(exception_message), success=0), 400


@api.route("/api/login/password", methods=["POST"], strict_slashes=False)
def login_password():
    """
    Route for logging in with a password

    JSON body::

        {
            "session_id": "uuid",
            "data": "secure_password",
        }

    :return: The next stage of the login sequence or an error message
    """
    # Perform standard validation on the request
    validate_out = helpers.input_validate_login(request, "session_id", "password")
    if isinstance(validate_out[0], flask.Response):
        return validate_out
    else:
        user: models.User = validate_out[0]
        session: models.LoginSession = validate_out[1]
        request_data: dict = validate_out[2]

    # Validate the password
    if not request_data.get('data', None) or not user.check_password(request_data.get('data', None)):
        helpers.create_failed_login_event(session, text="Invalid password entered.")
        return jsonify(msg="Invalid password, please try again.", success=0), 401
    else:
        # If the password is valid, move to the next stage of the login sequence
        helpers.progress_to_next_auth_stage(session, "password")
        next_stage = helpers.get_next_auth_stage(session)
        auth_id = None
        if next_stage is None:
            auth_session = helpers.create_auth_session(user)
            auth_id = auth_session.session_id
        return jsonify(msg="Password validated.", next=next_stage, auth_session_id=auth_id, success=1), 200


@api.route("/api/login/motion_pattern/unique", methods=["POST"], strict_slashes=False)
def login_motion_pattern_unique():
    """
    Route for validating whether a pico_id is unique

    JSON body::

        {
            "pico_id": "uuid",
        }

    :return: Whether the pico_id is unique or not
    """
    # Validate that the request is JSON
    try:
        request_data = helpers.json_validate(request)
    except AssertionError as exception_message:
        return jsonify(msg='Error: {}.'.format(exception_message), success=0), 400

    # Check that the pico_id is unique
    if helpers.check_pico_id_unique(request_data.get('pico_id', None)):
        return jsonify(msg="Pico ID is unique.", success=1), 200
    else:
        return jsonify(msg="Pico ID is not unique.", success=0), 400


@api.route("/api/login/motion_pattern/initialize", methods=["POST"], strict_slashes=False)
def login_motion_pattern():
    """
    Route for initializing a motion pattern login

    JSON body::

        {
            "session_id": "uuid",
            "pico_id": "uuid",
            "data": ["direction", "direction", "direction", ...],
        }

    - ``pico_id``: The ID of the pico to use for the motion pattern
    - ``data``: The added moves to the motion pattern

    :return: The next stage of the login sequence or an error message
    """
    # Perform standard validation on the request
    validate_out = helpers.input_validate_login(request, "session_id", "motion_pattern")
    if isinstance(validate_out[0], flask.Response):
        return validate_out
    else:
        user: models.User = validate_out[0]
        session: models.LoginSession = validate_out[1]
        request_data: dict = validate_out[2]

    # Add the pico_id and added sequence to the session
    helpers.add_pico_to_session(session, request_data)
    session = helpers.retry_motion_pattern(session, False)

    # Repeatedly check the session for completion of the motion pattern or a retry
    count = 0
    poll_seconds = 3

    while not session.motion_pattern_completed and not session.motion_pattern_retry:
        db.session.expire_all()
        session = helpers.get_login_session_from_id(uuid.UUID(request_data.get('session_id', None)))
        count += 1
        if count > constants.MOTION_PATTERN_TIMEOUT_SECONDS / poll_seconds:
            helpers.create_failed_login_event(session, text="Motion pattern timed out.")
            return jsonify(msg="Motion pattern timed out, please retry.", success=0), 401
        time.sleep(poll_seconds)

    # If the motion needs to be retried, clear the pico from the session and return
    if session.motion_pattern_retry:
        helpers.clear_pico_from_session(session)
        return jsonify(msg="Motion pattern incorrect, please retry.", success=0), 401
    if session.motion_pattern_completed:
        # If the password is valid, move to the next stage of the login sequence
        helpers.progress_to_next_auth_stage(session, "motion_pattern")
        next_stage = helpers.get_next_auth_stage(session)
        auth_id = None
        if next_stage is None:
            auth_session = helpers.create_auth_session(user)
            auth_id = auth_session.session_id
        return jsonify(msg="Motion pattern validated.", next=next_stage, auth_session_id=auth_id, success=1), 200


@api.route("/api/login/motion_pattern/validate", methods=["POST"], strict_slashes=False)
def login_motion_pattern_validate():
    """
    Route for validating a motion pattern login

    JSON body::

        {
            "pico_id": "uuid",
            "data": ["direction", "direction", "direction", ...],

    - ``data``: The motion pattern to validate (user pattern + added moves)

    :return: The next stage of the login sequence or an error message
    """
    # Perform standard validation on the request
    validate_out = helpers.input_validate_login(request, "pico_id", "motion_pattern", session_method="pico_id")
    if isinstance(validate_out[0], flask.Response):
        return validate_out
    else:
        user: models.User = validate_out[0]
        session: models.LoginSession = validate_out[1]
        request_data: dict = validate_out[2]

    # Validate the motion pattern
    if not request_data.get('data', None):
        helpers.retry_motion_pattern(session, True)
        helpers.create_failed_login_event(session, text="No motion pattern field entered.")
        return jsonify(msg="No motion pattern field entered, please try again.", success=0), 400

    # Split the motion pattern into the base pattern and the added sequence
    split_pattern = helpers.split_motion_pattern(session, request_data.get('data', None))

    # Check if the base pattern and added sequence are correct
    if (not user.check_motion_pattern(str(split_pattern[0]))
            or not session.motion_added_sequence.strip('][').replace('"', '').split(', ') == split_pattern[1]):
        helpers.retry_motion_pattern(session, True)
        if not user.check_motion_pattern(str(split_pattern[0])):
            helpers.create_failed_login_event(session, text="Incorrect base motion pattern entered.")
        else:
            helpers.create_failed_login_event(session, text="Incorrect added motion sequence entered.")
        return jsonify(msg="Incorrect motion pattern, please try again.", success=0), 401
    else:
        # If the motion pattern is valid, move to the next stage of the login sequence
        helpers.complete_motion_pattern(session, True)
        return jsonify(msg="Motion pattern validated.", success=1), 200


@api.route("/api/login/face_recognition", methods=["POST"], strict_slashes=False)
def login_face_recognition():
    """
    Route for logging in with face recognition

    Form body:

    - ``session_id``: The session ID of the login session
    - ``photo``: The photo to use for face recognition

    :return: The next stage of the login sequence or an error message
    """
    # Perform standard validation on the request
    validate_out = helpers.input_validate_login(request, "session_id", "face_recognition", "multipart/form-data")
    if isinstance(validate_out[0], flask.Response):
        return validate_out
    else:
        user: models.User = validate_out[0]
        session: models.LoginSession = validate_out[1]

    # Check if a photo was submitted
    file = request.files.get('photo', None)

    if file is None:
        helpers.create_failed_login_event(session, text="No photo submitted.")
        return jsonify(msg="No photo submitted, please try again.", success=0), 400

    # Check if the facial recognition passes
    if not user.check_face_recognition(file):
        helpers.create_failed_login_event(session, text="Face recognition match failed.", photo=file)
        return jsonify(msg="Face recognition match failed, please try again.", success=0), 401
    else:
        # If the facial recognition passes, move to the next stage of the login sequence
        helpers.save_face_recognition_photo(session, file)
        helpers.progress_to_next_auth_stage(session, "face_recognition")
        next_stage = helpers.get_next_auth_stage(session)
        auth_id = None
        if next_stage is None:
            auth_session = helpers.create_auth_session(user)
            auth_id = auth_session.session_id
        return jsonify(msg="Face recognition validated.", next=next_stage, auth_session_id=auth_id, success=1), 200


@api.route("/api/client/validate", methods=["POST"], strict_slashes=False)
def client_validate():
    """
    Route for a client to check that their ``auth_session_id`` is valid

    JSON body::

        {
            "auth_session_id": "uuid"
        }

    :return: Whether the ``auth_session_id`` is valid or not
    """
    # Validate that the request is JSON
    try:
        request_data = helpers.json_validate(request)
    except AssertionError as exception_message:
        return jsonify(msg='Error: {}.'.format(exception_message), success=0), 400

    if not request_data.get('auth_session_id', None):
        return jsonify(msg="Missing auth_session_id in request.", success=0), 400

    auth_session: models.AuthSession = helpers.get_auth_session_from_id(
        uuid.UUID(request_data.get('auth_session_id', None)))

    if auth_session is None:
        return jsonify(msg="Invalid auth_session_id, please try again.", success=0), 401
    elif (datetime.datetime.now() - datetime.timedelta(minutes=float(constants.AUTH_SESSION_EXPIRY_MINUTES))
          > auth_session.date):
        return jsonify(msg="Session expired, please start a new login session.", next="email", success=0), 401

    return jsonify(msg="Auth session ID is valid.", success=1), 200


###################################################################################
#                             Admin Dashboard Routes                              #
###################################################################################
@api.route("/health", strict_slashes=False)
def health():
    """Health check route for the backend server"""
    return Response("OK", status=200)


@api.route("/api/dashboard/failed_events", methods=["GET"], strict_slashes=False)
def get_failed_events():
    """
    Route for getting failed login events

    If both email and session_id are provided, the email will be used.

    Query params:

    - ``email``: The email of the user to get failed events for (optional)
    - ``session_id``: The session ID of the login session (optional)

    :return: The failed events for the user
    """
    email: str = request.args.get('email', None)
    session_id: str = request.args.get('session_id', None)

    user = None
    session = None

    if email is not None:
        user = helpers.get_user_from_email(email)
        if user is None:
            return jsonify(msg="Invalid email, please try again.", success=0), 401
    elif session_id is not None:
        session = helpers.get_login_session_from_id(uuid.UUID(session_id))
        if session is None:
            return jsonify(msg="Invalid session_id, please try again.", success=0), 401

    events = helpers.get_failed_login_events_as_dict(user, session)

    return jsonify(msg="Failed events retrieved.", success=1, events=events), 200