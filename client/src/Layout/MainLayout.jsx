import React from 'react';
import { Outlet } from 'react-router-dom';
import VerticalNavbar from '../components/VerticalNavbar';
import { useLocation } from 'react-router-dom';

const MainLayout = () => {
  const location = useLocation();
  const isHomePage = location.pathname === '/';
  const hideNavbar = location.pathname === '/login' || location.pathname === '/regiter' || location.pathname === '/create';


  return (
    <div className="flex flex-col md:flex-row">
      <VerticalNavbar />
      <div className="w-[70px]"/> {/* Matches the CSS width */}
      
      {/* Main content section */}
      <div className="flex-1">
        <Outlet />
      </div>
    </div>
  );
};

export default MainLayout;