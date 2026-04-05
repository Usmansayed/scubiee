"use client"

import React, { useState } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { Check } from "lucide-react"
import { GrLinkNext } from "react-icons/gr";
const cloud = import.meta.env.VITE_CLOUD_URL;

const categories  = [
  "Politics", "Technology", "Sports", "Social Media", "Business", 
  "Science", "Health", "Entertainment", "World News", "Local News", 
  "Environment", "Education", "Crime", "Law & Justice", "Culture", 
  "Travel", "Food & Cuisines", "Fashion", "Lifestyle", "Automobile", 
  "Space & Astronomy", "History", "Finance", "Real Estate", "Social Issues", 
  "Startups & Entrepreneurship", "Gaming", "Military & Defense", 
  "Religion & Spirituality"
];

const transitionProps = {
  type: "spring",
  stiffness: 500,
  damping: 30,
  mass: 0.5,
}

export default function CuisineSelector({ onSubmitCategories }) {
  const [selected, setSelected] = useState([])

  const toggleCuisine = (cuisine) => {
    setSelected((prev) =>
      prev.includes(cuisine)
        ? prev.filter((c) => c !== cuisine)
        : [...prev, cuisine]
    )
  }

  const handleSubmit = () => {
    onSubmitCategories(selected)
  }

  return (
    <div className="min-h-screen md:p-6 p-2 md:pt-40">
      <h1 className="text-gray-200 text-3xl font-semibold md:mr-44 mb-6 500:mb-12 max-500:text-2xl text-center">
        Which news topics interest you?
      </h1>
      <div className="max-w-[640px] mx-auto relative">
        <motion.div className="flex flex-wrap gap-3 overflow-visible" layout transition={transitionProps}>
          {categories.map((cuisine) => {
            const isSelected = selected.includes(cuisine)
            return (
              <motion.button
                key={cuisine}
                onClick={() => toggleCuisine(cuisine)}
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
                  <span>{cuisine}</span>
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
        <button
          onClick={handleSubmit}
          className="absolute bottom-[-80x] mt-4 500:mt-8 right-6  mr-4 bg-white text-black font-sans font-[500] rounded-full px-4 py-2 shadow-sm"
        >
          Submit<GrLinkNext className="inline-block ml-2 mb-1" />
        </button>
      </div>
    </div>
  )
}