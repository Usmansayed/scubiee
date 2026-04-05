import React from "react";
import { Search } from "lucide-react";
import VerticalNavbar from "../components/VerticalNavbar"; // Adjust the import path as needed

function Feed() {
  const filters = [
    { label: "All", count: 28 },
    { label: "News", count: 12 },
    { label: "Announcements", count: 12 },
    { label: "Strategy", count: 7 },
    { label: "Operations", count: 15 },
    { label: "Metrics & Performance", count: 15 },
    { label: "Marketing", count: 7 },
    { label: "Automation", count: 4 },
  ];

  const blogCards = [
    {
      category: "Announcements",
      title: "THERE'S A NEW KID IN TOWN",
      description:
        "We are very excited to introduce you to aKidCalledBeast. Please join us to learn all about the aKidCalledBeast game and upcoming private sale and IGO on the Seedify Launchpad on March...",
      date: "20 Mar 2023",
      readTime: "5 min",
      image: "https://www.w3schools.com/html/pic_trulli.jpg",
      backgroundColor: "#f4f4f4",
      latest: true,
    },
    {
      category: "News",
      title: "MULTINFT LAUNCHES",
      description:
        "Over the next weeks we will release info on the 8 playable races in Mist's metaverse.",
      date: "19 Mar 2023",
      readTime: "2 min",
      image: "https://www.w3schools.com/w3images/mac.jpg",
      backgroundColor: "#dc2626",
    },
    {
      category: "Strategy",
      title: "BUILDING THE FUTURE",
      description:
        "Learn about our roadmap and strategic vision for the next quarter.",
      date: "18 Mar 2023",
      readTime: "4 min",
      image: "https://picsum.photos/seed/picsum/536/354",
      backgroundColor: "#0ea5e9",
    },
    {
      category: "Operations",
      title: "SYSTEM UPGRADE",
      description:
        "Important information about our upcoming system maintenance and improvements.",
      date: "17 Mar 2023",
      readTime: "3 min",
      image: "https://img.freepik.com/free-psd/international-coffee-day-landing-page-template_23-2149622396.jpg?t=st=1733755824~exp=1733759424~hmac=2463fb8ffaece5e6b232423f69645a7468c3d79e371498f35addf633a28e095e&w=1380",
      backgroundColor: "#8b5cf6",
    },
  ];

  return (
    <div className="flex min-h-screen  bg-[#111] text-white">
      <VerticalNavbar />
      <main className="flex-1 p-4 max-w-[94%] mx-auto">
        {/* Filters and Search */}
        <div className="grid gap-8 md:grid-cols-2">
          <div className="space-y-4">
            <h2 className="text-[20px] font-semibold">FILTERS</h2>
            <div className="flex flex-wrap gap-2">
              {filters.map((filter) => (
                <span
                  key={filter.label}
                  className="px-3 py-1 text-sm font-medium bg-black/50 rounded-full cursor-pointer hover:bg-gray-600"
                >
                  {filter.label} • {filter.count}
                </span>
              ))}
            </div>
          </div>
          <div className="space-y-4 w-full">
            <h2 className="text-lg font-semibold">SEARCH BLOG</h2>
            <div className="relative w-80">
              <Search className="absolute  h-4 text-gray-400 left-3 top-3" />
              <input
                type="text"
                placeholder="I want to read about..."
                className="pl-10 pr-3 bg-[#201f22] rounded-lg h-9 text-sm border-none focus:ring-2 focus:ring-gray-600"
              />
            </div>
          </div>
        </div>

        {/* Blog Cards */}
        <div className="grid gap-4 mt-8 md:grid-cols-2 lg:grid-cols-3">
          {blogCards.map((card, index) => (
            <div
              key={index}
              className={`p-4 transition-transform transform  bg-black/30 backdrop-blur-lg rounded-lg cursor-pointer ${
                card.latest ? "md:col-span-2" : ""
              }`}
            >
              <img
                src={card.image}
                alt={card.title}
                className="object-cover w-full h-48 rounded-lg"
              />
              <div className="mt-4">
                <div className="flex items-center justify-between mb-2">
                  <span className="px-2 py-1 text-xs font-semibold bg-gray-700 rounded-full">
                    {card.category}
                  </span>
                  {card.latest && (
                    <span className="px-2 py-1 text-xs font-semibold text-red-500 bg-red-100 rounded-full">
                      LATEST
                    </span>
                  )}
                </div>
                <h3 className="mb-2 text-lg font-bold">{card.title}</h3>
                <p className="mb-4 text-sm text-gray-400">{card.description}</p>
                <div className="text-sm text-gray-500">
                  <span>{card.date}</span> <span>•</span>{" "}
                  <span>{card.readTime} read</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      </main>
    </div>
  );
}

export default Feed;