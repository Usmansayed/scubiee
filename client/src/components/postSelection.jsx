"use client"

import React, { useState } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { Check } from "lucide-react"
import { GrLinkNext } from "react-icons/gr";
import { useDispatch, useSelector } from 'react-redux';
import { resetForm } from '../Slices/WidgetSlice';
import { FaArrowLeft } from 'react-icons/fa';
import { FaCheck, FaArrowRightLong } from 'react-icons/fa6';
const cloud = import.meta.env.VITE_CLOUD_URL;

const transitionProps = {
  type: "spring",
  stiffness: 500,
  damping: 30,
  mass: 0.5,
}

const categories  = [
  "Politics", "Technology", "Sports", "Social Media", "Business", 
  "Science", "Health", "Entertainment", "World News", "Local News", 
  "Environment", "Education", "Crime", "Law & Justice", "Culture", 
  "Travel", "Food & Cuisines", "Fashion", "Lifestyle", "Automobile", 
  "Space & Astronomy", "History", "Finance", "Real Estate", "Social Issues", 
  "Startups & Entrepreneurship", "Gaming", "Military & Defense", 
  "Religion & Spirituality"
];


export default function CuisineSelector({ onSubmitCategories, isSubmitting }) {
  const [selectedCategories, setSelectedCategories] = useState([]);
  const formData = useSelector((state) => state.widget.formData);
  const formType = useSelector((state) => state.widget.formType);
  const dispatch = useDispatch();

  const toggleCategory = (category) => {
    if (selectedCategories.includes(category)) {
      setSelectedCategories(selectedCategories.filter((c) => c !== category));
    } else {
      if (selectedCategories.length < 6) {
        setSelectedCategories([...selectedCategories, category]);
      }
    }
  };

  const handleSubmit = () => {
    if (selectedCategories.length === 0) {
      // Default to "General" if no category is selected
      onSubmitCategories(["General"]);
    } else {
      onSubmitCategories(selectedCategories);
    }
  };

  const handleGoBack = () => {
    // Go back to the form but keep form data
    dispatch(resetForm());
  }

  return (
    <div className="min-h-screen md:p-6 p-2 md:pt-40 overflow-y-auto max-h-screen scrollba-hidden scrollbar-hidden">
      <button 
        onClick={handleGoBack}
        className="fixed z-50 bg-[#111] top-4 max-500:left-2 max-500:top-3 left-4  text-gray-400 hover:text-white p-2 rounded-full"
      >
        <FaArrowLeft className="text-xl md:text-2xl" />
      </button>
      <h1 className="text-gray-200 text-3xl font-semibold md:mr-[280px] max-md:mt-4 max-500:mt-2 mb-6 500:mb-12 max-500:text-2xl text-center">
        What's Your Post About? 
      </h1>
      <div className="max-w-[640px] mx-auto relative">
        <motion.div className="flex flex-wrap gap-3 overflow-visible" layout transition={transitionProps}>
          {categories.map((category) => {
            const isSelected = selectedCategories.includes(category)
            return (
              <motion.button
                key={category}
                onClick={() => toggleCategory(category)}
                layout
                initial={false}
                animate={{
                  backgroundColor: isSelected ? "#1e3a8a" : "rgba(39, 39, 42, 0.5)",
                }}
                whileHover={{
                  backgroundColor: isSelected ? "#1e3a8a" : "rgba(39, 39, 42, 0.8)",
                }}
                whileTap={{
                  backgroundColor: isSelected ? "#172554" : "rgba(39, 39, 42, 0.9)",
                }}
                transition={{
                  ...transitionProps,
                  backgroundColor: { duration: 0.1 },
                }}
                className={`
                  inline-flex items-center px-4 py-2 rounded-full text-base text-[14.5px] font-medium
                  whitespace-nowrap overflow-hidden ring-1 ring-inset
                  ${isSelected ? "text-blue-300 ring-blue-500" : "text-zinc-400 ring-zinc-700"}
                `}
              >
                <motion.div
                  className="relative flex items-center"
                  animate={{
                    width: isSelected ? "auto" : "100%",
                    paddingRight: isSelected ? "1.5rem" : "0",
                  }}
                  transition={{
                    ease: [0.175, 0.885, 0.32, 1.275],
                    duration: 0.3,
                  }}
                >
                  <span>{category}</span>
                  <AnimatePresence>
                    {isSelected && (
                      <motion.span
                        initial={{ scale: 0, opacity: 0 }}
                        animate={{ scale: 1, opacity: 1 }}
                        exit={{ scale: 0, opacity: 0 }}
                        transition={transitionProps}
                        className="absolute right-0"
                      >
                        <div className="w-4 h-4 rounded-full bg-blue-300 flex items-center justify-center">
                          <Check className="w-3 h-3 text-blue-900" strokeWidth={1.5} />
                        </div>
                      </motion.span>
                    )}
                  </AnimatePresence>
                </motion.div>
              </motion.button>
            )
          })}
        </motion.div>
        <div className="flex justify-between mt-8">
          
          <button
            onClick={handleSubmit}
            disabled={isSubmitting}
            className="px-[22px] py-[10px] rounded-full bg-gray-300 text-gray-800 font-semibold hover:bg-gray-400 flex items-center"
          >
            {isSubmitting ? 'Publishing...' : 'Publish'}
            <FaArrowRightLong className="ml-2" />
          </button>
        </div>
      </div>
    </div>
  )
}