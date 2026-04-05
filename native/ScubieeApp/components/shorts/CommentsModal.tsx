import React, { useState, useEffect, useRef } from 'react';
import {
  Modal,
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  FlatList,
  TextInput, // Import TextInput type
  KeyboardAvoidingView,
  Platform,
  ActivityIndicator
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons, AntDesign } from '@expo/vector-icons';
import { fetchShortComments, commentOnShort } from '../../services/shortsService';
import CommentItem from './comments/CommentItem';

// Define a basic type for Comment - replace with your actual type
interface CommentAuthor {
  id: string;
  username: string;
  profilePicture: string;
}

interface Comment {
  id: string;
  content: string;
  createdAt: string;
  author: CommentAuthor;
  likes: number;
  isLiked: boolean;
  isOwner: boolean;
}

interface CommentsModalProps {
  visible: boolean;
  shortId: string;
  onClose: () => void;
}

export default function CommentsModal({ visible, shortId, onClose }: CommentsModalProps) {
  const [comments, setComments] = useState<Comment[]>([]); // Type the comments state
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null); // Type the error state
  const [newComment, setNewComment] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  
  const inputRef = useRef<TextInput>(null); // Type the input ref
  
  // Load comments
  const loadComments = async (pageNum: number = 1, refresh: boolean = false) => { // Type parameters
    if ((pageNum > 1 && !hasMore) || (loading && !refresh)) return;
    
    try {
      setLoading(true);
      if (refresh) setRefreshing(true);
      
      // Assume fetchShortComments returns { comments: Comment[], hasMore?: boolean }
      const response = await fetchShortComments(shortId, pageNum); 
      
      if (response && response.comments) {
        if (refresh || pageNum === 1) {
          setComments(response.comments);
        } else {
          setComments(prev => [...prev, ...response.comments]);
        }
        
        // Use hasMore from response if available, otherwise calculate
        const hasMoreFromServer = response.hasMore !== undefined ? response.hasMore : (response.comments?.length === 20);
        setHasMore(hasMoreFromServer); 
        setPage(pageNum);
      } else {
        // Handle case where response or response.comments is missing
        if (pageNum === 1) setComments([]);
        setHasMore(false);
      }
    } catch (err) {
      console.error('Error loading comments:', err);
      // Safely access error message
      const message = err instanceof Error ? err.message : 'An unknown error occurred';
      setError(`Failed to load comments: ${message}. Please try again.`);
    } finally {
      setLoading(false);
      if (refresh) setRefreshing(false);
    }
  };
  
  // Submit a new comment
  const handleSubmitComment = async () => {
    if (!newComment.trim() || submitting) return;
    
    try {
      setSubmitting(true);
      
      // Optimistic update - add comment to the list immediately
      const tempId = `temp-${Date.now()}`;
      const tempComment: Comment = {
        id: tempId,
        content: newComment,
        createdAt: new Date().toISOString(),
        author: {
          // This would come from your auth context in a real app
          id: 'current-user',
          username: 'You',
          profilePicture: 'https://randomuser.me/api/portraits/lego/1.jpg'
        },
        likes: 0,
        isLiked: false,
        isOwner: true
      };
      
      setComments(prev => [tempComment, ...prev]);
      setNewComment('');
      
      // Send to API
      const response = await commentOnShort(shortId, newComment);
      
      // Replace temp comment with the real one from the API
      if (response && response.comment) {
        setComments(prev => 
          prev.map(comment => 
            comment.id === tempId ? response.comment : comment
          )
        );
      }
    } catch (error) {
      console.error('Error posting comment:', error);
      
      // Remove the temp comment on error
      setComments(prev => 
        prev.filter(comment => !comment.id?.startsWith('temp-'))
      );
      
      // Put the text back in the input
      setNewComment(newComment);
    } finally {
      setSubmitting(false);
    }
  };

  // Refresh comments
  const handleRefresh = () => {
    loadComments(1, true);
  };

  // Load more comments
  const handleLoadMore = () => {
    if (!loading && hasMore) {
      loadComments(page + 1);
    }
  };
  
  // Load comments when modal opens
  useEffect(() => {
    if (visible && shortId) {
      loadComments(1);
    }
  }, [visible, shortId]);

  if (!visible) return null;

  return (
    <Modal
      animationType="slide"
      transparent={false}
      visible={visible}
      onRequestClose={onClose}
    >
      <SafeAreaView style={styles.safeArea}>
        <View style={styles.header}>
          <Text style={styles.headerTitle}>Comments</Text>
          <TouchableOpacity onPress={onClose} style={styles.closeButton}>
            <Ionicons name="close" size={24} color="#000" />
          </TouchableOpacity>
        </View>
        
        {loading && comments.length === 0 ? (
          <View style={styles.loadingContainer}>
            <ActivityIndicator size="large" color="#000" />
          </View>
        ) : error ? (
          <View style={styles.errorContainer}>
            <Text style={styles.errorText}>{error}</Text>
            <TouchableOpacity onPress={handleRefresh}>
              <Text style={styles.retryText}>Try Again</Text>
            </TouchableOpacity>
          </View>
        ) : (
          <FlatList
            data={comments}
            renderItem={({ item }) => <CommentItem comment={item} />}
            keyExtractor={item => item.id}
            contentContainerStyle={styles.commentsList}
            refreshing={refreshing}
            onRefresh={handleRefresh}
            onEndReached={handleLoadMore}
            onEndReachedThreshold={0.5}
            ListEmptyComponent={
              <View style={styles.emptyContainer}>
                <Text style={styles.emptyText}>No comments yet. Be the first!</Text>
              </View>
            }
            ListFooterComponent={
              loading && comments.length > 0 ? (
                <View style={styles.footerLoader}>
                  <ActivityIndicator size="small" color="#000" />
                </View>
              ) : null
            }
          />
        )}

        <KeyboardAvoidingView
          behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
          keyboardVerticalOffset={Platform.OS === 'ios' ? 90 : 0}
          style={styles.inputContainer}
        >
          <TextInput
            ref={inputRef}
            style={styles.input}
            placeholder="Add a comment..."
            value={newComment}
            onChangeText={setNewComment}
            multiline
            maxLength={300}
          />
          <TouchableOpacity
            style={[
              styles.postButton,
              (!newComment.trim() || submitting) && styles.disabledButton
            ]}
            onPress={handleSubmitComment}
            disabled={!newComment.trim() || submitting}
          >
            {submitting ? (
              <ActivityIndicator size="small" color="#fff" />
            ) : (
              <Text style={styles.postButtonText}>Post</Text>
            )}
          </TouchableOpacity>
        </KeyboardAvoidingView>
      </SafeAreaView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: '#fff',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    borderBottomWidth: 1,
    borderBottomColor: '#f0f0f0',
    paddingVertical: 12,
    position: 'relative',
  },
  headerTitle: {
    fontSize: 18,
    fontWeight: 'bold',
  },
  closeButton: {
    position: 'absolute',
    right: 16,
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
    marginBottom: 10,
  },
  retryText: {
    fontSize: 16,
    color: '#3897f0',
    fontWeight: '600',
  },
  commentsList: {
    flexGrow: 1,
    paddingHorizontal: 16,
  },
  emptyContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 20,
    height: 200,
  },
  emptyText: {
    fontSize: 16,
    color: '#666',
    textAlign: 'center',
  },
  footerLoader: {
    paddingVertical: 20,
    alignItems: 'center',
  },
  inputContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 10,
    borderTopWidth: 1,
    borderTopColor: '#f0f0f0',
    backgroundColor: '#fff',
  },
  input: {
    flex: 1,
    borderWidth: 1,
    borderColor: '#ddd',
    borderRadius: 20,
    paddingHorizontal: 15,
    paddingVertical: 8,
    maxHeight: 100,
  },
  postButton: {
    marginLeft: 10,
    backgroundColor: '#3897f0',
    paddingVertical: 8,
    paddingHorizontal: 15,
    borderRadius: 4,
    justifyContent: 'center',
    alignItems: 'center',
  },
  disabledButton: {
    backgroundColor: '#b2dffc',
  },
  postButtonText: {
    color: '#fff',
    fontWeight: '600',
  },
});