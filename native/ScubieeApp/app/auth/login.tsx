import React, { useState } from 'react';
import { 
  View, 
  Text, 
  TextInput, 
  TouchableOpacity, 
  StyleSheet, 
  Image, 
  ActivityIndicator, 
  Alert,
  KeyboardAvoidingView,
  Platform,
  ScrollView
} from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaView } from 'react-native-safe-area-context';
import { router, Link } from 'expo-router';
import { login } from '../../services/authService';

export default function LoginScreen() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleLogin = async () => {
    if (!email.trim() || !password.trim()) {
      setError('Please fill in all fields');
      return;
    }

    try {
      setLoading(true);
      setError('');
      
      await login(email, password);
      
      // Navigate to main app
      router.replace('/');
    } catch (err) {
      console.error('Login Error:', err);
      setError((err as any)?.message || 'Failed to login. Please check your credentials.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <SafeAreaView style={styles.container}>
      <StatusBar style="dark" />
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        style={styles.keyboardAvoidingView}
      >
        <ScrollView contentContainerStyle={styles.scrollView}>
          <View style={styles.logoContainer}>
            <Image
              source={require('../../assets/images/logo.png')}
              style={styles.logo}
              resizeMode="contain"
            />
            <Text style={styles.appName}>Scubiee</Text>
          </View>

          <View style={styles.formContainer}>
            {error ? <Text style={styles.errorText}>{error}</Text> : null}
            
            <TextInput
              style={styles.input}
              placeholder="Email"
              placeholderTextColor="#999"
              value={email}
              onChangeText={setEmail}
              keyboardType="email-address"
              autoCapitalize="none"
              autoCorrect={false}
            />

            <TextInput
              style={styles.input}
              placeholder="Password"
              placeholderTextColor="#999"
              value={password}
              onChangeText={setPassword}
              secureTextEntry
              autoCapitalize="none"
              autoCorrect={false}
            />

            <TouchableOpacity 
              style={styles.forgotPassword}
              onPress={() => router.push('/auth/forgot-password')}
            >
              <Text style={styles.forgotPasswordText}>Forgot password?</Text>
            </TouchableOpacity>

            <TouchableOpacity 
              style={[
                styles.loginButton,
                (!email.trim() || !password.trim()) ? styles.disabledButton : null
              ]}
              onPress={handleLogin}
              disabled={loading || !email.trim() || !password.trim()}
            >
              {loading ? (
                <ActivityIndicator color="#fff" size="small" />
              ) : (
                <Text style={styles.loginButtonText}>Log In</Text>
              )}
            </TouchableOpacity>
          </View>

          <View style={styles.signupContainer}>
            <Text style={styles.signupText}>Don't have an account? </Text>
            <Link href="/auth/register" asChild>
              <TouchableOpacity>
                <Text style={styles.signupLink}>Sign up</Text>
              </TouchableOpacity>
            </Link>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#fff',
  },
  keyboardAvoidingView: {
    flex: 1,
  },
  scrollView: {
    flexGrow: 1,
    paddingHorizontal: 20,
    justifyContent: 'center',
  },
  logoContainer: {
    alignItems: 'center',
    marginBottom: 40,
  },
  logo: {
    width: 100,
    height: 100,
  },
  appName: {
    fontSize: 24,
    fontWeight: 'bold',
    marginTop: 10,
  },
  formContainer: {
    width: '100%',
  },
  errorText: {
    color: '#ff3b30',
    marginBottom: 10,
    textAlign: 'center',
  },
  input: {
    borderWidth: 1,
    borderColor: '#ddd',
    borderRadius: 8,
    paddingVertical: 12,
    paddingHorizontal: 16,
    marginBottom: 15,
    fontSize: 16,
  },
  forgotPassword: {
    alignSelf: 'flex-end',
    marginBottom: 20,
  },
  forgotPasswordText: {
    color: '#3897f0',
    fontSize: 14,
    fontWeight: '500',
  },
  loginButton: {
    backgroundColor: '#3897f0',
    borderRadius: 8,
    paddingVertical: 15,
    alignItems: 'center',
  },
  disabledButton: {
    backgroundColor: '#b2dffc',
  },
  loginButtonText: {
    color: '#fff',
    fontWeight: '600',
    fontSize: 16,
  },
  signupContainer: {
    flexDirection: 'row',
    marginTop: 30,
    justifyContent: 'center',
  },
  signupText: {
    fontSize: 14,
    color: '#333',
  },
  signupLink: {
    fontSize: 14,
    fontWeight: '600',
    color: '#3897f0',
  },
});