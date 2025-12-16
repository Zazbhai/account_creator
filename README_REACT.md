# Account Creator - React Frontend Setup

This application now uses React for the frontend with real-time updates via WebSocket and skeleton loading on all pages.

## Setup Instructions

### 1. Install Python Dependencies

```bash
pip install -r requirements.txt
```

### 2. Install Node.js Dependencies

```bash
npm install
```

### 3. Build React App

For development (with hot reload):
```bash
npm run dev
```

For production build:
```bash
npm run build
```

### 4. Run the Backend

The backend serves the React app and handles WebSocket connections:

```bash
python app_backend.py
```

The app will be available at:
- Frontend (development): http://localhost:3000
- Backend API: http://localhost:5000

## Features

### Real-time Updates
- All changes are reflected immediately without page refresh
- Logs update in real-time via WebSocket
- Balance and worker status update automatically

### Skeleton Loading
- All pages show skeleton loaders while data is being fetched
- Smooth transitions from loading to content
- Better user experience during data loading

### Pages
- **Login**: User authentication
- **Launcher**: Start account creation with real-time logs
- **IMAP Settings**: Configure IMAP credentials
- **Reports**: View account creation reports
- **Logs**: View all logs in real-time
- **Admin Dashboard**: Admin overview
- **User Management**: Create/delete users (admin only)

## Development

### Running Both Frontend and Backend

**Terminal 1** (Backend):
```bash
python app_backend.py
```

**Terminal 2** (Frontend - Development):
```bash
npm run dev
```

### Production Deployment

1. Build the React app:
```bash
npm run build
```

2. The backend (`app_backend.py`) will automatically serve the built React app from the `dist` folder.

3. Run the backend:
```bash
python app_backend.py
```

The app will be available at http://localhost:5000

## WebSocket Events

The backend emits the following WebSocket events:
- `log`: New log line
- `balance`: Balance update
- `worker_status`: Worker running status
- `connected`: Connection confirmation

## Notes

- The old `app.py` is preserved as a backup
- Use `app_backend.py` for the new React-based application
- All API endpoints are prefixed with `/api`
- WebSocket connections are handled via Socket.IO
