# API Documentation Guide

## 🚀 Quick Start

Your IITD Agent Backend now has comprehensive Swagger/OpenAPI documentation with interactive testing capabilities and **updated DevClub OAuth integration**!

## 📖 Available Documentation

### 1. Enhanced Swagger UI (Recommended)
**URL**: `http://localhost:8000/docs-advanced`

**Features**:
- 🔐 Persistent authorization (remembers your login)
- 🔗 Deep linking support
- 📊 Extended model details and examples
- ⚡ Enhanced testing capabilities
- 📱 Better responsive design

### 2. Standard Swagger UI  
**URL**: `http://localhost:8000/docs`

**Features**:
- 📝 Standard OpenAPI interface
- 🧪 Interactive endpoint testing
- 📋 Auto-generated examples

### 3. ReDoc Documentation
**URL**: `http://localhost:8000/redoc`

**Features**:
- 📖 Clean, readable documentation format
- 📱 Mobile-friendly design
- 🔍 Searchable content

### 4. OpenAPI Schema
**URL**: `http://localhost:8000/openapi.json`

Raw OpenAPI 3.0 specification for programmatic access.

## 🔑 DevClub OAuth Authentication Guide

### Setup Requirements

1. **Register Your Application**:
   - Visit https://oauth.devclub.in/
   - Click "Get Started" and log in with admin credentials
   - Register your client with necessary grant types
   - Save your `client_id`, `client_secret`, and `grant_type`

2. **Environment Configuration**:
   ```bash
   CLIENT_ID=your_devclub_client_id_here
   CLIENT_SECRET=your_devclub_client_secret_here
   JWT_SECRET=change-me-in-prod
   ```

### Authentication Flow

#### Complete OAuth Integration Example

**Frontend Implementation**:
```javascript
// Step 1: Get DevClub OAuth signin URL
async function initiateLogin() {
    const redirectUri = 'http://localhost:3000/callback';
    const response = await fetch(`/auth/signin-url?redirect_uri=${encodeURIComponent(redirectUri)}`);
    const { signin_url } = await response.json();
    
    // Step 2: Redirect user to DevClub OAuth
    window.location.href = signin_url;
}

// Step 3: Handle OAuth callback (in your /callback route)
async function handleCallback() {
    const urlParams = new URLSearchParams(window.location.search);
    const code = urlParams.get('code');
    const state = urlParams.get('state');
    
    if (!code || !state) {
        throw new Error('Missing OAuth parameters');
    }
    
    // Step 4: Exchange code for JWT token
    const response = await fetch('/auth/callback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code, state })
    });
    
    if (response.ok) {
        const { access_token, token_type } = await response.json();
        
        // Step 5: Store token and use for API calls
        localStorage.setItem('authToken', access_token);
        
        // Redirect to main app
        window.location.href = '/dashboard';
    }
}

// Step 6: Use token in API calls
async function makeAuthenticatedRequest(endpoint, options = {}) {
    const token = localStorage.getItem('authToken');
    return fetch(endpoint, {
        ...options,
        headers: {
            ...options.headers,
            'Authorization': `Bearer ${token}`
        }
    });
}
```

#### API Testing in Swagger UI

1. **Get Signin URL**: Test `/auth/signin-url` endpoint
2. **Visit OAuth URL**: Copy the returned URL and visit it in browser
3. **Complete OAuth**: Authenticate with DevClub and get callback with code/state
4. **Exchange for Token**: Use `/auth/callback` with the code and state
5. **Authorize in Swagger**: Click "🔒 Authorize" and enter `Bearer <your-jwt-token>`
6. **Test Protected Endpoints**: All endpoints now include your authentication

### User Data from DevClub OAuth

The new integration provides comprehensive user information:

```javascript
// User object structure from OAuth
{
    "id": "user_id",
    "oauthId": "user_oauth_id", 
    "name": "user_name",
    "email": "aa1200001@iitd.ac.in",
    "hostel": "user_hostel",
    "kerberos": "aa1200001", 
    "dateOfBirth": "user_dob",
    "instagramId": "user_instagramId",
    "mobileNo": "9876543210"
}
```

## 📋 API Categories

### System
- `GET /health` - Health check endpoint

### Authentication  
- `GET /auth/signin-url` - Get DevClub OAuth signin URL
- `POST /auth/callback` - Process OAuth callback and return JWT token

### Chat Management
- `POST /chats` - Create empty chat session
- `GET /chats` - List user's chat sessions  
- `GET /chats/{chat_id}` - Get specific chat details
- `POST /chats/new` - Create chat with first message (recommended)
- `DELETE /chats/{chat_id}` - Delete chat session

### Messages
- `POST /chats/{chat_id}/messages` - Send message to AI agent
- `GET /chats/{chat_id}/messages` - Get conversation history

### Admin - Document Management
- `POST /admin/documents` - Upload and process PDF documents
- `GET /admin/documents` - List all documents
- `GET /admin/documents/{doc_id}` - Get document details
- `DELETE /admin/documents/{doc_id}` - Delete document

## 💡 Pro Tips

1. **Use Enhanced Docs**: The `/docs-advanced` endpoint provides the best testing experience
2. **Persistent Auth**: Once you authorize in enhanced docs, you stay logged in
3. **Real Examples**: All schemas include realistic example data with DevClub user fields
4. **Error Handling**: Each endpoint documents expected error responses
5. **Status Codes**: Full HTTP status code documentation for each endpoint
6. **OAuth Testing**: Use the signin-url endpoint to get the OAuth URL for testing

## 🏃‍♂️ Running the Server

```bash
cd /path/to/backend
source .venv/bin/activate
uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

Then visit: `http://localhost:8000/docs-advanced`

## 🎯 Complete Testing Workflow

1. **Setup Environment**: Configure CLIENT_ID and CLIENT_SECRET
2. **Start Server**: Run with uvicorn
3. **Visit Enhanced Docs**: `http://localhost:8000/docs-advanced`
4. **Test Signin URL**: Use `/auth/signin-url?redirect_uri=http://localhost:3000/callback`
5. **Visit OAuth URL**: Copy signin URL and complete DevClub authentication
6. **Get Callback Data**: Note the `code` and `state` parameters from callback
7. **Exchange for Token**: Test `/auth/callback` with the code and state
8. **Authorize in Swagger**: Click "🔒 Authorize" and enter `Bearer <token>`
9. **Test Chat Flow**:
   - Create chat: `/chats/new` 
   - Send messages: `/chats/{chat_id}/messages`
   - View history: `GET /chats/{chat_id}/messages`

## 🔧 Migration Notes

If upgrading from previous OAuth implementation:

1. **URL Changed**: `iitdoauth.vercel.app` → `oauth.devclub.in`
2. **New Endpoint**: Added `/auth/signin-url` for getting OAuth URL
3. **Enhanced User Model**: Now includes hostel, kerberos, mobile, etc.
4. **Same Token Flow**: JWT tokens work the same way
5. **Backward Compatible**: Existing user emails will be linked to new OAuth data

Happy API testing with DevClub OAuth! 🎉