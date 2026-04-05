import { useEffect } from 'react';
import { useDispatch } from 'react-redux';
import { useNavigate } from 'react-router-dom';
import { checkAuth } from './Slices/UserSlice';

const AuthProvider = ({ children }) => {
  const dispatch = useDispatch();
  const navigate = useNavigate();

  useEffect(() => {
    console.log('Checking auth...'); // Debug log
    dispatch(checkAuth())
      .unwrap()
      .catch((error) => {
        console.log('Auth check failed:', error); // Debug log
        navigate('/sign-in');
      });
  }, [dispatch, navigate]);

  return children;
};

export default AuthProvider;