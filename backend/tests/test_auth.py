import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_register_user_success(async_client: AsyncClient):
    response = await async_client.post(
        "/register",
        json={
            "username": "testuser",
            "password": "testpassword",
            "email": "test@example.com"
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert "user_id" in data

@pytest.mark.asyncio
async def test_register_user_duplicate_username(async_client: AsyncClient):
    # Register the first user
    await async_client.post(
        "/register",
        json={
            "username": "duplicateuser",
            "password": "testpassword",
            "email": "first@example.com"
        }
    )
    # Attempt to register with the same username but a different email
    response = await async_client.post(
        "/register",
        json={
            "username": "duplicateuser",
            "password": "newpassword",
            "email": "second@example.com"
        }
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Username already exists"

@pytest.mark.asyncio
async def test_register_user_duplicate_email(async_client: AsyncClient):
    # Register the first user
    await async_client.post(
        "/register",
        json={
            "username": "user1",
            "password": "testpassword",
            "email": "duplicate@example.com"
        }
    )
    # Attempt to register with a different username but the same email
    response = await async_client.post(
        "/register",
        json={
            "username": "user2",
            "password": "newpassword",
            "email": "duplicate@example.com"
        }
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Email already exists"

@pytest.mark.asyncio
async def test_login_user_success(async_client: AsyncClient):
    # Register a user
    await async_client.post(
        "/register",
        json={
            "username": "loginuser",
            "password": "loginpassword",
            "email": "login@example.com"
        }
    )
    # Attempt to log in
    response = await async_client.post(
        "/login",
        json={
            "email": "login@example.com",
            "password": "loginpassword"
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"

@pytest.mark.asyncio
async def test_login_user_invalid_password(async_client: AsyncClient):
    # Register a user
    await async_client.post(
        "/register",
        json={
            "username": "invaliduser",
            "password": "correctpassword",
            "email": "invalid@example.com"
        }
    )
    # Attempt to log in with wrong password
    response = await async_client.post(
        "/login",
        json={
            "email": "invalid@example.com",
            "password": "wrongpassword"
        }
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password"

@pytest.mark.asyncio
async def test_get_me_success(async_client: AsyncClient):
    # Register a user
    register_response = await async_client.post(
        "/register",
        json={
            "username": "meuser",
            "password": "mepassword",
            "email": "me@example.com"
        }
    )
    token = register_response.json()["access_token"]

    # Request /me with the token
    response = await async_client.get(
        "/me",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["username"] == "meuser"
    assert data["email"] == "me@example.com"

@pytest.mark.asyncio
async def test_get_me_unauthorized(async_client: AsyncClient):
    # Request /me without a token
    response = await async_client.get("/me")
    assert response.status_code == 401
    assert response.json()["detail"] == "Not authenticated"
