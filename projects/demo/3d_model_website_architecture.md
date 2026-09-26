# 3D Model Website Architecture

## Frontend
- **Framework**: React
- **3D Library**: Three.js
- **Features**: Model viewer, drag-and-drop upload, real-time rendering

## Backend
- **Language**: Node.js (Express)
- **API Endpoints**:
  - `/models/upload` - Upload 3D models
  - `/models/list` - List available models
  - `/models/view` - Render a model

## Database
- **Storage**: MongoDB (for metadata)
- **File Storage**: AWS S3 (for 3D model files)

## Security
- Authentication via OAuth 2.0
- Model file validation (e.g., .glb, .obj)

## Deployment
- Frontend: Vercel
- Backend: Heroku
- Database: MongoDB Atlas