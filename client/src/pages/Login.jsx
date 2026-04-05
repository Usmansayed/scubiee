import React, { useState, useRef, useEffect } from 'react';
import { Formik, Form } from 'formik';
import { TextField, Button, Select, MenuItem, FormControl, InputLabel, Box } from '@mui/material';
import * as Yup from 'yup';
import axios from 'axios';
import { FaPen } from "react-icons/fa";
import { IoMdArrowDropdown } from "react-icons/io";
import CuisineSelector from '../components/selection'; // Adjust path if needed
import './Login.css';

const api = import.meta.env.VITE_API_URL;

const statesOfIndia = [
  "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa", 
  "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala", 
  "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya", "Mizoram", "Nagaland", 
  "Odisha", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura", 
  "Uttar Pradesh", "Uttarakhand", "West Bengal"
];

const initialValues = {
  username: '',
  firstName: '',
  lastName: '',
  state: ''
};

const CompleteProfile = () => {
  const DefaultPicture = "/logos/DefaultPicture.png";
  const [previewImage, setPreviewImage] = useState(DefaultPicture);
  const fileInputRef = useRef(null);
  const [step, setStep] = useState(1);
  const [formData, setFormData] = useState(initialValues);
  const [usernameAvailable, setUsernameAvailable] = useState(null);
  const [checkingUsername, setCheckingUsername] = useState(false);
  const [formSubmitAttempted, setFormSubmitAttempted] = useState(false);
  const cloud = import.meta.env.VITE_CLOUD_URL;

  useEffect(() => {
    axios.get(`${api}/user`, { withCredentials: true })
      .then(res => {
        if (res.data && res.data.id) {
          window.location.replace('/');
        }
      })
      .catch(() => {});
  }, []);

  const validationSchema = Yup.object().shape({
    username: Yup.string()
      .min(4, 'Username must be at least 4 characters')
      .max(16, 'Username cannot exceed 16 characters')
      .matches(
        /^[a-zA-Z0-9._]+$/, 
        'Username can only contain letters, numbers, periods, and underscores'
      )
      .required('Username is required'),
    firstName: Yup.string()
      .max(20, 'First name cannot exceed 20 characters')
      .required('First name is required'),
    lastName: Yup.string()
      .max(20, 'Last name cannot exceed 20 characters')
      .required('Last name is required'),
    state: Yup.string().required('State is required')
  });
  
  const handleUsernameChange = (e, handleChange) => {
    handleChange(e);
    
    if (formSubmitAttempted) {
      setUsernameAvailable(null);
    }
  };

  const handleFormSubmit = async (data) => {
    setFormSubmitAttempted(true);
    
    if (!data.username || data.username.length < 4) {
      return;
    }
    
    const usernameRegex = /^[a-zA-Z0-9._]+$/;
    if (!usernameRegex.test(data.username) || data.username.length > 16) {
      return;
    }
    
    setCheckingUsername(true);
    
    try {
      const { data: checkResult } = await axios.get(`${api}/user/check-username`, {
        params: { username: data.username },
      });
      
      setUsernameAvailable(checkResult.available);
      
      if (checkResult.available) {
        setFormData(data);
        setStep(2);
      }
    } catch (error) {
      console.error('Error checking username:', error);
    } finally {
      setCheckingUsername(false);
    }
  };

  const handleCategories = (selectedCategories) => {
    const finalData = { ...formData, categories: selectedCategories };
    const formDataToSend = new FormData();
    formDataToSend.append('username', finalData.username);
    formDataToSend.append('firstName', finalData.firstName);
    formDataToSend.append('lastName', finalData.lastName);
    formDataToSend.append('state', finalData.state);
    formDataToSend.append('categories', JSON.stringify(finalData.categories));

    if (fileInputRef.current && fileInputRef.current.files && fileInputRef.current.files[0]) {
      formDataToSend.append('profilePic', fileInputRef.current.files[0]);
    }

    axios.post(`${api}/user/complete-profile`, formDataToSend, {
      withCredentials: true,
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    .then((response) => {
      if (response.data.success) {
        // Replace current history state and navigate
        window.history.replaceState(null, '', '/');
        window.location.href = '/';
      }
    })
    .catch((error) => {
      console.error('Error completing profile', error);
    });
  };

  const handleImageClick = () => {
    if (fileInputRef.current) fileInputRef.current.click();
  };

  const handleFileChange = (event) => {
    const file = event.target.files[0];
    if (file) {
      // Check file size
      const maxSize = 10 * 1024 * 1024;
      if (file.size > maxSize) {
        alert("Profile picture cannot exceed 10MB in size");
        event.target.value = null;
        return;
      }
      
      // Check file type
      const allowedTypes = ['image/jpeg', 'image/jpg', 'image/png'];
      if (!allowedTypes.includes(file.type)) {
        alert("Only JPG, JPEG, and PNG image formats are allowed");
        event.target.value = null;
        return;
      }
      
      const reader = new FileReader();
      reader.onloadend = () => setPreviewImage(reader.result);
      reader.readAsDataURL(file);
    }
  };

  return (
    <div className="flex login flex-col bg-[#0a0a0a] justify-center items-center min-h-screen max-md:p-2">
      <input
        type="file"
        ref={fileInputRef}
        onChange={handleFileChange}
        className="hidden"
        accept="image/*"
      />

      {step === 1 && (
        <>
          <h1 className="top-6 fixed text-[28px] font-sans font-semibold text-white mb-20 max-lg:mb-10">
            Complete Your Profile
          </h1>
          <div className="relative">
            <div className="w-32 h-32 md:w-40 md:h-40 max-md:mt-12 rounded-full mb-10 overflow-hidden border-4 border-zinc-300 relative">
              <img
                onClick={handleImageClick}
                src={previewImage}
                className="object-cover bg-gray-300 w-full h-full"
                alt="Profile"
              />
            </div>
            <div
              className="absolute bottom-11 right-1 border-4 border-gray-300 bg-gray-100 p-[6px] rounded-full cursor-pointer"
              onClick={handleImageClick}
            >
              <FaPen className="text-black w-5 h-5 max-md:w-[18px] max-md:h-[18px] font-bold" />
            </div>
          </div>
          <Formik
            initialValues={initialValues}
            onSubmit={(values) => handleFormSubmit(values)}
            validationSchema={validationSchema}
            validateOnChange={false}
            validateOnBlur={false}
          >
            {({ handleSubmit, handleChange, values, errors, touched }) => (
              <Form
                className="bg-[#0c0c0c] max-md:mb-20 border-[1px] md:border-2 border-[#303541] p-8 max-md:p-6
                           rounded-3xl shadow-md w-full max-w-md"
              >
                <Box sx={{ display: 'flex', gap: 2, marginBottom: 2 }}>
                  <TextField
                    fullWidth
                    label="First Name"
                    name="firstName"
                    value={values.firstName}
                    onChange={handleChange}
                    error={touched.firstName && Boolean(errors.firstName)}
                    helperText={touched.firstName && errors.firstName}
                    variant="outlined"
                    className="custom-textfieldd"
                  />
                  <TextField
                    fullWidth
                    label="Last Name"
                    name="lastName"
                    value={values.lastName}
                    onChange={handleChange}
                    error={touched.lastName && Boolean(errors.lastName)}
                    helperText={touched.lastName && errors.lastName}
                    variant="outlined"
                    className="custom-textfieldd"
                  />
                </Box>

                <div className="mb-4 relative">
                  <TextField
                    fullWidth
                    label="Username"
                    name="username"
                    value={values.username}
                    onChange={(e) => handleUsernameChange(e, handleChange)}
                    error={(touched.username && Boolean(errors.username)) || 
                           (formSubmitAttempted && usernameAvailable === false)}
                    helperText={(touched.username && errors.username) || 
                               (formSubmitAttempted && usernameAvailable === false && 
                                "This username is already taken")}
                    variant="outlined"
                    className="custom-textfieldd"
                  />
                  {checkingUsername && (
                    <div className="absolute right-2 top-4">
                      <svg
                        className="animate-spin h-5 w-5 text-white"
                        xmlns="http://www.w3.org/2000/svg"
                        fill="none"
                        viewBox="0 0 24 24"
                      >
                        <circle
                          className="opacity-25"
                          cx="12"
                          cy="12"
                          r="10"
                          stroke="currentColor"
                          strokeWidth="4"
                        ></circle>
                        <path
                          className="opacity-75"
                          fill="currentColor"
                          d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                        ></path>
                      </svg>
                    </div>
                  )}
                </div>
                
                {formSubmitAttempted && usernameAvailable === true && (
                  <p className="mt-[-12px] mb-2 text-sm text-green-500">
                    Username is available
                  </p>
                )}

                <div className="mb-4">
                  <FormControl fullWidth variant="outlined" className="custom-textfieldd">
                    <InputLabel>State</InputLabel>
                    <Select
                      label="State"
                      name="state"
                      value={values.state}
                      onChange={handleChange}
                      error={touched.state && Boolean(errors.state)}
                      IconComponent={IoMdArrowDropdown}
                      MenuProps={{
                        PaperProps: {
                          sx: {
                            bgcolor: '#333',
                            color: 'white'
                          }
                        }
                      }}
                    >
                      {statesOfIndia.map((st, idx) => (
                        <MenuItem key={idx} value={st}>{st}</MenuItem>
                      ))}
                    </Select>
                    {touched.state && errors.state && (
                      <p style={{ color: 'red', fontSize: '0.8rem' }}>
                        {errors.state}
                      </p>
                    )}
                  </FormControl>
                </div>

                <Button
                  type="submit"
                  onClick={handleSubmit}
                  fullWidth
                  variant="contained"
                  sx={{
                    marginTop: '16px',
                    marginBottom: '16px',
                    borderRadius: '16px',
                    backgroundColor: '#d3d3d3',
                    color: 'black'
                  }}
                  disabled={checkingUsername}
                >
                  Next
                </Button>
              </Form>
            )}
          </Formik>
        </>
      )}

      {step === 2 && (
        <CuisineSelector onSubmitCategories={handleCategories} />
      )}
    </div>
  );
};

export default CompleteProfile;