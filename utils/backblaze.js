const {Storage} = require('@google-cloud/storage');
const path = require('path');
const crypto = require('crypto');
const fs = require('fs');

// Create a local fallback directory for when GCS is unavailable
const FALLBACK_DIR = path.join(__dirname, '../uploads');
if (!fs.existsSync(FALLBACK_DIR)) {
  fs.mkdirSync(FALLBACK_DIR, { recursive: true });
}

// Path to your service account credentials JSON file
const CREDENTIALS_PATH = process.env.GOOGLE_APPLICATION_CREDENTIALS || 
                        path.join(__dirname, '../config/gcloud-key.json');

// Initialize the storage client
let storage = null;
let bucket = null;
let isGCSAvailable = true; // Track whether GCS is available

// Function to initialize the Google Cloud Storage client
const initGCS = () => {
  try {
    if (!fs.existsSync(CREDENTIALS_PATH)) {
      console.error(`GCS credentials file not found at: ${CREDENTIALS_PATH}`);
      isGCSAvailable = false;
      return false;
    }

    storage = new Storage({
      keyFilename: CREDENTIALS_PATH,
    });
    
    // Get the bucket
    bucket = storage.bucket(process.env.GCS_BUCKET_NAME);
    
    return true;
  } catch (error) {
    console.error('GCS Initialization Error:', error.message);
    isGCSAvailable = false;
    return false;
  }
};

// Test connection to GCS - can be called on startup
const testGCSConnection = async () => {
  try {
    if (!process.env.GCS_BUCKET_NAME) {
      console.error('GCS Configuration Missing: GCS_BUCKET_NAME not defined in .env file');
      isGCSAvailable = false;
      return false;
    }
    
    // Initialize the GCS client
    if (!initGCS()) {
      return false;
    }
    
    // Test if we can access the bucket
    const [exists] = await bucket.exists();
    if (!exists) {
      console.error(`Bucket ${process.env.GCS_BUCKET_NAME} does not exist`);
      isGCSAvailable = false;
      return false;
    }
    
    console.log('GCS Connection Verified:', {
      bucketName: process.env.GCS_BUCKET_NAME
    });
    isGCSAvailable = true;
    return true;
  } catch (error) {
    console.error('GCS Connection Test Failed:', error.message);
    isGCSAvailable = false;
    return false;
  }
};

// Function to upload a file to GCS with local fallback
const uploadToGCS = async (buffer, filename, virtualFolder) => {
  try {
    if (!isGCSAvailable) {
      return uploadToLocal(buffer, filename, virtualFolder);
    }

    if (!buffer || buffer.length === 0) {
      throw new Error('Empty file buffer provided');
    }

    // Initialize if not already initialized
    if (!storage || !bucket) {
      if (!initGCS()) {
        return uploadToLocal(buffer, filename, virtualFolder);
      }
    }
    
    // Create a full path including the virtual folder
    const fullPath = virtualFolder ? `${virtualFolder}/${filename}` : filename;
    
    // Create a file in the bucket
    const file = bucket.file(fullPath);
    
    // Upload the file content
    await file.save(buffer, {
      contentType: getContentTypeByExtension(path.extname(filename)),
      metadata: {
        cacheControl: 'public, max-age=31536000', // Cache for 1 year
      },
    });
    
    // REMOVED: Do not call makePublic() when using uniform bucket-level access
    
    // Construct the downloadable URL based on the bucket's public access configuration
    const downloadUrl = `https://storage.googleapis.com/${process.env.GCS_BUCKET_NAME}/${fullPath}`;
    
    return {
      filename: fullPath,
      url: downloadUrl,
      fileId: fullPath, // In GCS, the path serves as a unique identifier
    };
  } catch (error) {
    console.error('GCS upload failed, using local fallback:', error.message);
    return uploadToLocal(buffer, filename, virtualFolder);
  }
};

// Fallback function to save to local filesystem
const uploadToLocal = async (buffer, filename, virtualFolder) => {
  try {
    const folderPath = path.join(FALLBACK_DIR, virtualFolder || '');
    if (!fs.existsSync(folderPath)) {
      fs.mkdirSync(folderPath, { recursive: true });
    }
    
    const filePath = path.join(folderPath, filename);
    await fs.promises.writeFile(filePath, buffer);
    
    // Generate a local URL (this will be relative to your server)
    const localUrl = `/uploads/${virtualFolder ? virtualFolder + '/' : ''}${filename}`;
    
    return {
      filename: filename,
      url: localUrl,
      isLocalFallback: true
    };
  } catch (error) {
    console.error('Local fallback upload failed:', error);
    throw new Error(`Failed to upload file: ${error.message}`);
  }
};

// Function to delete a file from GCS with fallback
const deleteFromGCS = async (filename, virtualFolder) => {
  try {
    if (!isGCSAvailable) {
      return deleteFromLocal(filename, virtualFolder);
    }

    // Initialize if not already initialized
    if (!storage || !bucket) {
      if (!initGCS()) {
        return deleteFromLocal(filename, virtualFolder);
      }
    }
    
    // Create a full path including the virtual folder
    const fullPath = virtualFolder ? `${virtualFolder}/${filename}` : filename;
    
    // Get the file reference
    const file = bucket.file(fullPath);
    
    // Check if file exists
    const [exists] = await file.exists();
    if (exists) {
      await file.delete();
      return true;
    }
    return false;
  } catch (error) {
    console.error('GCS deletion failed, using local fallback:', error.message);
    return deleteFromLocal(filename, virtualFolder);
  }
};

// Fallback function to delete from local filesystem
const deleteFromLocal = async (filename, virtualFolder) => {
  try {
    const folderPath = path.join(FALLBACK_DIR, virtualFolder || '');
    const filePath = path.join(folderPath, filename);
    
    if (fs.existsSync(filePath)) {
      await fs.promises.unlink(filePath);
      return true;
    }
    return false;
  } catch (error) {
    console.error('Local fallback deletion failed:', error);
    return false;
  }
};

// Helper function to get content type based on file extension
const getContentTypeByExtension = (ext) => {
  const contentTypeMap = {
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.png': 'image/png',
    '.gif': 'image/gif',
    '.mp4': 'video/mp4',
    '.mov': 'video/quicktime',
    '.pdf': 'application/pdf',
    // Add more as needed
  };
  return contentTypeMap[ext.toLowerCase()] || 'application/octet-stream';
};

// Generate a unique filename
const generateUniqueFilename = (originalFilename) => {
  const ext = path.extname(originalFilename);
  const randomName = crypto.randomBytes(32).toString('hex');
  return `${randomName}${ext}`;
};

// Add a utility function to generate URLs from just filenames
const getGCSUrl = (filename, folder) => {
  if (!filename) return null;
  const bucketName = process.env.GCS_BUCKET_NAME;
  const fullPath = folder ? `${folder}/${filename}` : filename;
  return `https://storage.googleapis.com/${bucketName}/${fullPath}`;
};

module.exports = {
  uploadToB2: uploadToGCS, // Maintain backward compatible API
  deleteFromB2: deleteFromGCS, // Maintain backward compatible API
  generateUniqueFilename,
  testB2Connection: testGCSConnection, // Maintain backward compatible API
  getB2Url: getGCSUrl // Maintain backward compatible API
};
