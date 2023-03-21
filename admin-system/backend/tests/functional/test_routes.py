import datetime
import io
import os
import uuid
from unittest.mock import patch

import pytest

import api.helpers
import constants


@pytest.mark.get_request
def test_index(test_client):
    response = test_client.get("/api")
    assert response.status_code == 200


@pytest.mark.get_request
def test_health(test_client):
    response = test_client.get("/health")
    assert response.status_code == 200


@pytest.mark.get_request
def test_server_error(test_client):
    response = test_client.get("/api/doesnt_exist")
    assert response.status_code == 500


@pytest.mark.post_request
@pytest.mark.parametrize("endpoint", [
    "/api/signup",
    "/api/login/email",
    "/api/login/password",
    "/api/login/motion_pattern/unique",
    "/api/login/motion_pattern/initialize",
    "/api/login/motion_pattern/validate",
    "/api/login/face_recognition",
    "/api/client/validate",
])
def test_not_json(test_client, endpoint):
    """
    Tests that the server returns a 400 error when the request is not JSON
    """
    response = test_client.post(endpoint, data={"data": "data"})
    assert response.status_code == 400


@pytest.mark.database
@pytest.mark.post_request
@pytest.mark.parametrize("email, password, motion_pattern, auth_methods, expected_result", [
    ("a@ab.com", "password", ["direction"], [True, True, True], 400),  # Invalid password (no uppercase and number)
    ("b@bc.ca", "Password1", ["up"], [True, True, False], 200),  # Valid user
    ("c@de.cl", "Password1", ["down"], [False, False, True], 200),  # Valid user
    ("only@motion.com", "Password1", ["up"], [False, True, False], 200),  # Valid user
    ("slaj@slj.lka", "Sakjlkjd3", ["left", "right"], [True, False, False], 200),  # Valid user
])
def test_user_create(test_client, email, password, motion_pattern, auth_methods, expected_result):
    """
    Tests the user creation endpoint
    """
    response = test_client.post("/api/signup", json={
        "email": email,
        "password": password,
        "motion_pattern": motion_pattern,
        "auth_methods": {
            "password": auth_methods[0],
            "motion_pattern": auth_methods[1],
            "face_recognition": auth_methods[2]
        }
    })
    assert response.status_code == expected_result


@pytest.mark.database
@pytest.mark.post_request
@pytest.mark.parametrize("email, password, date, expected_result", [
    (None, "Password1", datetime.datetime.now(), 400),  # No session
    ("c@de.cl", "Password1", datetime.datetime.now(), 400),  # Wrong stage
    ("b@bc.ca", "Password1", datetime.datetime.now(), 200),  # Valid user
    ("b@bc.ca", "Password1", datetime.datetime.now() - datetime.timedelta(minutes=6), 401),  # Expired session
])
def test_input_validation(test_client, email, password, date, expected_result):
    """
    Tests that the server returns errors in different cases
    """
    if email is None:
        session = None
    else:
        user = api.helpers.get_user_from_email(email)
        session = api.helpers.create_login_session(user)
        session.date = date

    data = {
        "session_id": session.session_id if session else uuid.uuid4(),
        "data": password
    }

    response = test_client.post("/api/login/password", json=data)
    assert response.status_code == expected_result


@pytest.mark.database
@pytest.mark.post_request
@pytest.mark.parametrize("email, expected_result", [
    ("b@bc.ca", 200),  # Valid user
    ("c@de.cl", 200),  # Valid user
    ("notfound@user.com", 401),  # User not found
    ("invalidemail", 401),  # Invalid email
])
def test_user_login_email(test_client, email, expected_result):
    """
    Tests the user email login endpoint
    """
    response = test_client.post("/api/login/email", json={
        "data": email,
    })
    assert response.status_code == expected_result


@pytest.mark.database
@pytest.mark.post_request
@pytest.mark.parametrize("email, password, expected_result", [
    ("b@bc.ca", "Password1", 200),  # Valid user
    ("slaj@slj.lka", "Sakjlkjd3", 200),  # Valid user with no next stage
    ("b@bc.ca", "NotPassword1", 401),  # Wrong password
])
def test_user_login_password(test_client, email, password, expected_result):
    """
    Tests the user password login endpoint
    """
    user = api.helpers.get_user_from_email(email)
    session = api.helpers.create_login_session(user)

    response = test_client.post("/api/login/password", json={
        "session_id": session.session_id,
        "data": password,
    })
    assert response.status_code == expected_result


@pytest.mark.database
@pytest.mark.post_request
def test_user_login_motion_pattern_unique(test_client):
    """
    Tests the user motion pattern unique endpoint
    """
    pico_id = "ac022bac-45d5-477c-a90e-e4447155cef3"
    request_data = {
        "pico_id": pico_id,
        "data": ["up", "down", "left", "right"]
    }
    user = api.helpers.get_user_from_email("b@bc.ca")
    session = api.helpers.create_login_session(user)

    response = test_client.post("/api/login/motion_pattern/unique", json=request_data)

    assert response.status_code == 200

    api.helpers.add_pico_to_session(session, request_data)
    response = test_client.post("/api/login/motion_pattern/unique", json=request_data)

    assert response.status_code == 400


@pytest.mark.database
@pytest.mark.post_request
@pytest.mark.parametrize("seed, email, motion_added, pico_result, expected_result", [
    ("seed1", "only@motion.com", ["down"], "complete", 200),  # Valid user
    ("seed2", "only@motion.com", ["up"], "retry", 401),  # Wrong sequence
    ("seed3", "only@motion.com", ["up"], "timeout", 401),  # Timeout
])
@patch("api.helpers.retry_motion_pattern")
def test_user_login_motion_pattern(mock_retry, test_client, seed, email, motion_added, pico_result, expected_result):
    """
    Tests the user motion pattern login endpoint
    """
    pico_id = uuid.uuid5(namespace=uuid.uuid4(), name=seed)
    user = api.helpers.get_user_from_email(email)
    session = api.helpers.create_login_session(user)

    if pico_result == "complete":
        session.motion_pattern_completed = True
    elif pico_result == "retry":
        session.motion_pattern_retry = True
    else:
        constants.MOTION_PATTERN_TIMEOUT_SECONDS = 5

    # Mock the retry function to output an altered session to avoid the while loop
    mock_retry.return_value = session

    response = test_client.post("/api/login/motion_pattern/initialize", json={
        "session_id": str(session.session_id),
        "pico_id": str(pico_id),
        "data": motion_added,
    })

    assert response.status_code == expected_result


@pytest.mark.database
@pytest.mark.post_request
@pytest.mark.parametrize("seed, email, key, motion_pattern, motion_added, expected_result", [
    ("seed1", "only@motion.com", "data", ["up", "left", "right"], ["left", "right"], 200),  # Valid user
    ("seed2", "only@motion.com", "data", ["down", "up"], ["up"], 401),  # Wrong base sequence
    ("seed3", "only@motion.com", "data", ["up", "down"], ["left"], 401),  # Wrong added sequence
    ("seed4", "only@motion.com", "notdata", ["up", "down"], ["down"], 400),  # Invalid key
])
def test_user_login_motion_pattern_pico(test_client, seed, email, key, motion_pattern, motion_added, expected_result):
    """
    Tests the user motion pattern endpoint
    """
    pico_id = uuid.uuid5(namespace=uuid.uuid4(), name=seed)
    user = api.helpers.get_user_from_email(email)
    session = api.helpers.create_login_session(user)
    api.helpers.add_pico_to_session(session, {
        "pico_id": str(pico_id),
        "data": motion_added,
    })

    response = test_client.post("/api/login/motion_pattern/validate", json={
        "pico_id": str(pico_id),
        key: motion_pattern,
    })

    assert response.status_code == expected_result


@pytest.mark.database
@pytest.mark.post_request
@pytest.mark.parametrize("email, image, model_output, expected_result", [
    ("c@de.cl", "user1.png", True, 200),  # Valid user
    ("c@de.cl", "user1.png", False, 401),  # Invalid user
    ("c@de.cl", "no_photo", False, 400),  # No photo
])
@patch("api.models.User.check_face_recognition")
def test_user_login_face(mock_face, test_client, email, image, model_output, expected_result):
    """
    Tests the user face login endpoint
    """
    user = api.helpers.get_user_from_email(email)
    session = api.helpers.create_login_session(user)

    data = {}
    path = os.path.abspath(os.path.join(os.curdir, "tests", "images", image))
    if image != "no_photo":
        with open(path, 'rb') as photo:
            input_file_stream = io.BytesIO(photo.read())

        data['photo'] = (input_file_stream, image)
    data['request'] = '{"session_id": "' + str(session.session_id) + '"}'

    mock_face.return_value = model_output

    response = test_client.post("/api/login/face_recognition", content_type='multipart/form-data', data=data)
    assert response.status_code == expected_result


@pytest.mark.database
@pytest.mark.post_request
@pytest.mark.parametrize("email, key, auth_output, date, expected_result", [
    ("slaj@slj.lka", "auth_session_id", "valid", datetime.datetime.now(), 200),  # Valid user
    ("slaj@slj.lka", "auth_session_id", None, datetime.datetime.now(), 401),  # No session
    ("slaj@slj.lka", "no_key", "valid", datetime.datetime.now(), 400),  # No key
    ("slaj@slj.lka", "auth_session_id", "valid", datetime.datetime.now() - datetime.timedelta(days=1), 401),
    # Expired session
])
@patch("api.helpers.get_auth_session_from_id")
def test_auth_verify(mock_auth, test_client, email, key, auth_output, date, expected_result):
    """
    Tests the auth verify endpoint
    """
    user = api.helpers.get_user_from_email(email)
    session = api.helpers.create_auth_session(user)
    session.date = date

    if auth_output is None:
        mock_auth.return_value = None
    else:
        mock_auth.return_value = session

    response = test_client.post("/api/client/validate", json={
        key: session.session_id,
    })
    assert response.status_code == expected_result


@pytest.mark.database
@pytest.mark.get_request
@pytest.mark.parametrize("email, session_id, expected_result", [
    (None, None, 200),  # All events
    ("only@motion.com", None, 200),  # Valid email
    ("noemail@email.com", None, 401),  # Invalid email
    (None, uuid.uuid5(namespace=uuid.uuid4(), name="no_session"), 401),  # Invalid session
])
def test_get_failed_events(test_client, email, session_id, expected_result):
    """
    Tests the get failed events endpoint
    """
    data = {
        "email": email,
        "session_id": session_id,
    }
    response = test_client.get("/api/dashboard/failed_events", query_string=data)
    assert response.status_code == expected_result


@pytest.mark.database
@pytest.mark.post_request
def test_complete_login(test_client):
    """
    Tests a user fully logging in
    """
    user = api.helpers.get_user_from_email("slaj@slj.lka")
    session = api.helpers.create_login_session(user)

    response = test_client.post("/api/login/password", json={
        "session_id": str(session.session_id),
        "data": "Sakjlkjd3",
    })

    assert response.status_code == 200

    response = test_client.post("/api/login/password", json={
        "session_id": str(session.session_id),
        "data": "Sakjlkjd3",
    })

    assert response.status_code == 400