import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  Image,
  StyleSheet,
  TouchableOpacity,
  ScrollView,
  ActivityIndicator,
  Dimensions,
  RefreshControl,
  FlatList
} from 'react-native';
import { useLocalSearchParams } from 'expo-router';
import { Ionicons, Feather, MaterialIcons } from '@expo/vector-icons';
import { useAuth } from '../../contexts/AuthContext';
import { fetchUserProfile } from '../../services/userService';
import { fetchUserPosts } from '../../services/postsService';
import { fetchUserShorts } from '../../services/shortsService';
import PostGrid from '../../components/profile/PostGrid';
import ShortsRow from '../../components/profile/ShortsRow';

const { width } = Dimensions.get('window');

export default function ProfileScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { user: currentUser } = useAuth();
  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [activeTab, setActiveTab] = useState('posts');
  const [posts, setPosts] = useState([]);
  const [shorts, setShorts] = useState([]);
  const [saved, setSaved] = useState([]);
  const [followersCount, setFollowersCount] = useState(0);
  const [followingCount, setFollowingCount] = useState(0);
  const [isFollowing, setIsFollowing] = useState(false);
  const [error, setError] = useState(null);
  
  const isOwnProfile = currentUser?.id === id;
  
  // Placeholder function for saved posts (implement this in your services)
  const fetchSavedPosts = async () => {
    // Implement this in your services
    return { saved: [] };
  };

  // Load profile data
  const loadProfile = async (refresh = false) => {
    try {
      if (refresh) {
        setRefreshing(true);
      } else {
        setLoading(true);
      }
      
      // Fetch user profile data
      const profileData = await fetchUserProfile(id);
      setProfile(profileData);
      setFollowersCount(profileData.followersCount);
      setFollowingCount(profileData.followingCount);
      setIsFollowing(profileData.isFollowing);
      
      // Fetch posts and shorts based on active tab
      if (activeTab === 'posts' || refresh) {
        const postsData = await fetchUserPosts(id);
        setPosts(postsData.posts || []);
      }
      
      if (activeTab === 'shorts' || refresh) {
        const shortsData = await fetchUserShorts(id);
        setShorts(shortsData.shorts || []);
      }
      
      if (activeTab === 'saved' && isOwnProfile) {
        // API call for saved posts (only for own profile)
        const savedData = await fetchSavedPosts();
        setSaved(savedData.saved || []);
      }
      
      setError(null);
    } catch (err) {
      console.error('Error loading profile:', err);
      setError('Failed to load profile data. Please try again.');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };
  
  // Initial load
  useEffect(() => {
    loadProfile();
  }, [id]);
  
  // Handle tab change
  const handleTabChange = async (tab: string) => {
    setActiveTab(tab);
    
    // Load data for the selected tab if not already loaded
    try {
      if (tab === 'posts' && posts.length === 0) {
        setLoading(true);
        const postsData = await fetchUserPosts(id);
        setPosts(postsData.posts || []);
      } else if (tab === 'shorts' && shorts.length === 0) {
        setLoading(true);
        const shortsData = await fetchUserShorts(id);
        setShorts(shortsData.shorts || []);
      } else if (tab === 'saved' && saved.length === 0 && isOwnProfile) {
        setLoading(true);
        // API call for saved posts (only for own profile)
        const savedData = await fetchSavedPosts();
        setSaved(savedData.saved || []);
      }
    } catch (err) {
      console.error('Error changing tab:', err);
    } finally {
      setLoading(false);
    }
  };
  
  // Handle follow/unfollow
  const handleFollowToggle = async () => {
    // API call for follow/unfollow
    // For now, just toggle state
    setIsFollowing(!isFollowing);
    setFollowersCount(isFollowing ? followersCount - 1 : followersCount + 1);
  };
  
  // Handle pull to refresh
  const onRefresh = () => {
    loadProfile(true);
  };
  
  if (loading && !refreshing) {
    return (
      <View style={styles.loadingContainer}>
        <ActivityIndicator size="large" color="#000" />
      </View>
    );
  }
  
  if (error) {
    return (
      <View style={styles.errorContainer}>
        <Text style={styles.errorText}>{error}</Text>
        <TouchableOpacity onPress={() => loadProfile()}>
          <Text style={styles.retryText}>Try Again</Text>
        </TouchableOpacity>
      </View>
    );
  }
  
  return (
    <ScrollView 
      style={styles.container} 
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={onRefresh} />
      }
    >
      {/* Profile Header */}
      <View style={styles.profileHeader}>
        <Image 
          source={{ uri: profile?.profilePicture || 'https://randomuser.me/api/portraits/lego/1.jpg' }} 
          style={styles.profileImage} 
        />
        
        <View style={styles.profileStats}>
          <View style={styles.statItem}>
            <Text style={styles.statValue}>{posts.length || 0}</Text>
            <Text style={styles.statLabel}>Posts</Text>
          </View>
          
          <View style={styles.statItem}>
            <Text style={styles.statValue}>{followersCount}</Text>
            <Text style={styles.statLabel}>Followers</Text>
          </View>
          
          <View style={styles.statItem}>
            <Text style={styles.statValue}>{followingCount}</Text>
            <Text style={styles.statLabel}>Following</Text>
          </View>
        </View>
      </View>
      
      {/* Profile Info */}
      <View style={styles.profileInfo}>
        <Text style={styles.displayName}>{profile?.displayName || profile?.username}</Text>
        <Text style={styles.username}>@{profile?.username}</Text>
        
        {profile?.bio && (
          <Text style={styles.bio}>{profile.bio}</Text>
        )}
      </View>
      
      {/* Action Buttons */}
      <View style={styles.actions}>
        {isOwnProfile ? (
          <TouchableOpacity style={styles.editButton}>
            <Text style={styles.editButtonText}>Edit Profile</Text>
          </TouchableOpacity>
        ) : (
          <View style={styles.actionButtons}>
            <TouchableOpacity
              style={[
                styles.followButton,
                isFollowing && styles.followingButton
              ]}
              onPress={handleFollowToggle}
            >
              <Text 
                style={[
                  styles.followButtonText,
                  isFollowing && styles.followingButtonText
                ]}
              >
                {isFollowing ? 'Following' : 'Follow'}
              </Text>
            </TouchableOpacity>
            
            <TouchableOpacity style={styles.messageButton}>
              <Text style={styles.messageButtonText}>Message</Text>
            </TouchableOpacity>
          </View>
        )}
      </View>
      
      {/* Content Tabs */}
      <View style={styles.tabs}>
        <TouchableOpacity
          style={[
            styles.tabItem,
            activeTab === 'posts' && styles.activeTab
          ]}
          onPress={() => handleTabChange('posts')}
        >
          <Ionicons 
            name="grid-outline"
            size={22}
            color={activeTab === 'posts' ? '#000' : '#999'}
          />
        </TouchableOpacity>
        
        <TouchableOpacity
          style={[
            styles.tabItem,
            activeTab === 'shorts' && styles.activeTab
          ]}
          onPress={() => handleTabChange('shorts')}
        >
          <Feather 
            name="video"
            size={22}
            color={activeTab === 'shorts' ? '#000' : '#999'}
          />
        </TouchableOpacity>
        
        {isOwnProfile && (
          <TouchableOpacity
            style={[
              styles.tabItem,
              activeTab === 'saved' && styles.activeTab
            ]}
            onPress={() => handleTabChange('saved')}
          >
            <MaterialIcons 
              name="bookmark-outline"
              size={24}
              color={activeTab === 'saved' ? '#000' : '#999'}
            />
          </TouchableOpacity>
        )}
      </View>
      
      {/* Tab Content */}
      <View style={styles.contentContainer}>
        {activeTab === 'posts' && (
          posts.length > 0 ? (
            <PostGrid posts={posts} />
          ) : (
            <View style={styles.emptyContainer}>
              <Ionicons name="images-outline" size={60} color="#ccc" />
              <Text style={styles.emptyText}>No posts yet</Text>
            </View>
          )
        )}
        
        {activeTab === 'shorts' && (
          shorts.length > 0 ? (
            <ShortsRow shorts={shorts} />
          ) : (
            <View style={styles.emptyContainer}>
              <Feather name="video-off" size={60} color="#ccc" />
              <Text style={styles.emptyText}>No shorts yet</Text>
            </View>
          )
        )}
        
        {activeTab === 'saved' && isOwnProfile && (
          saved.length > 0 ? (
            <PostGrid posts={saved} />
          ) : (
            <View style={styles.emptyContainer}>
              <MaterialIcons name="bookmark-outline" size={60} color="#ccc" />
              <Text style={styles.emptyText}>No saved posts</Text>
            </View>
          )
        )}
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#fff',
  },
  loadingContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  errorContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 20,
  },
  errorText: {
    fontSize: 16,
    color: '#666',
    textAlign: 'center',
    marginBottom: 12,
  },
  retryText: {
    fontSize: 16,
    color: '#3897f0',
    fontWeight: '600',
  },
  profileHeader: {
    flexDirection: 'row',
    padding: 16,
    alignItems: 'center',
  },
  profileImage: {
    width: 80,
    height: 80,
    borderRadius: 40,
  },
  profileStats: {
    flex: 1,
    flexDirection: 'row',
    justifyContent: 'space-around',
    marginLeft: 16,
  },
  statItem: {
    alignItems: 'center',
  },
  statValue: {
    fontSize: 18,
    fontWeight: 'bold',
  },
  statLabel: {
    fontSize: 14,
    color: '#666',
  },
  profileInfo: {
    paddingHorizontal: 16,
    paddingBottom: 16,
  },
  displayName: {
    fontSize: 16,
    fontWeight: 'bold',
  },
  username: {
    fontSize: 14,
    color: '#666',
    marginBottom: 8,
  },
  bio: {
    fontSize: 14,
    lineHeight: 20,
  },
  actions: {
    paddingHorizontal: 16,
    paddingBottom: 16,
  },
  actionButtons: {
    flexDirection: 'row',
  },
  followButton: {
    flex: 1,
    backgroundColor: '#3897f0',
    borderRadius: 4,
    paddingVertical: 8,
    marginRight: 8,
    alignItems: 'center',
  },
  followingButton: {
    backgroundColor: '#fff',
    borderWidth: 1,
    borderColor: '#ddd',
  },
  followButtonText: {
    color: '#fff',
    fontWeight: '600',
  },
  followingButtonText: {
    color: '#000',
  },
  messageButton: {
    flex: 1,
    backgroundColor: '#fff',
    borderWidth: 1,
    borderColor: '#ddd',
    borderRadius: 4,
    paddingVertical: 8,
    alignItems: 'center',
  },
  messageButtonText: {
    fontWeight: '600',
  },
  editButton: {
    backgroundColor: '#fff',
    borderWidth: 1,
    borderColor: '#ddd',
    borderRadius: 4,
    paddingVertical: 8,
    alignItems: 'center',
  },
  editButtonText: {
    fontWeight: '600',
  },
  tabs: {
    flexDirection: 'row',
    borderTopWidth: 1,
    borderTopColor: '#eee',
    borderBottomWidth: 1,
    borderBottomColor: '#eee',
  },
  tabItem: {
    flex: 1,
    alignItems: 'center',
    paddingVertical: 12,
  },
  activeTab: {
    borderBottomWidth: 2,
    borderBottomColor: '#000',
  },
  contentContainer: {
    flex: 1,
    minHeight: 300,
  },
  emptyContainer: {
    padding: 40,
    alignItems: 'center',
    justifyContent: 'center',
  },
  emptyText: {
    marginTop: 10,
    fontSize: 16,
    color: '#999',
  },
});