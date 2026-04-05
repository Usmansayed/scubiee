import React, { useState } from 'react';
import { 
  View, 
  Text, 
  TextInput, 
  TouchableOpacity, 
  StyleSheet, 
  Image, 
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  ScrollView
} from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaView } from 'react-native-safe-area-context';
import { router, Link } from 'expo-router';
import { register } from '../../services/authService';

export default function RegisterScreen() {
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleRegister = async () => {
    // Form validation
    if (!username.trim() || !email.trim() || !password.trim() || !confirmPassword.trim()) {
      setError('Please fill in all fields');
      return;
    }

    if (password !== confirmPassword) {
      setError('Passwords do not match');
      return;
    }

    if (password.length < 8) {
      setError('Password must be at least 8 characters');
      return;
    }

    try {
      setLoading(true);
      setError('');
      
      await register({
        username,
        email,
        password
      });
      
      // Navigate to main app
      router.replace('/');
    } catch (err) {
      console.error('Registration Error:', err);
      setError((err as any)?.message || 'Failed to register. Please try again.');
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
            <Text style={styles.signUpTitle}>Create an account</Text>
          </View>

          <View style={styles.formContainer}>
            {error ? <Text style={styles.errorText}>{error}</Text> : null}
            
            <TextInput
              style={styles.input}
              placeholder="Username"
              placeholderTextColor="#999"
              value={username}
              onChangeText={setUsername}
              autoCapitalize="none"
              autoCorrect={false}
            />

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

            <TextInput
              style={styles.input}
              placeholder="Confirm Password"
              placeholderTextColor="#999"
              value={confirmPassword}
              onChangeText={setConfirmPassword}
              secureTextEntry
              autoCapitalize="none"
              autoCorrect={false}
            />

            <TouchableOpacity 
              style={[
                styles.registerButton, 
                (!username.trim() || !email.trim() || !password.trim() || !confirmPassword.trim()) 
                  ? styles.disabledButton 
                  : null
              ]}
              onPress={handleRegister}
              disabled={
                loading || 
                !username.trim() || 
                !email.trim() || 
                !password.trim() || 
                !confirmPassword.trim()
              }
            >
              {loading ? (
                <ActivityIndicator color="#fff" size="small" />
              ) : (
                <Text style={styles.registerButtonText}>Sign Up</Text>
              )}
            </TouchableOpacity>
          </View>

          <View style={styles.loginContainer}>
            <Text style={styles.loginText}>Already have an account? </Text>
            <Link href="/auth/login" asChild>
              <TouchableOpacity>
                <Text style={styles.loginLink}>Log in</Text>
              </TouchableOpacity>
            </Link>
          </View>

          <Text style={styles.termsText}>
            By signing up, you agree to our Terms of Service and Privacy Policy
          </Text>
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
    paddingTop: 20,
    paddingBottom: 40,
  },
  logoContainer: {
    alignItems: 'center',
    marginBottom: 30,
  },
  logo: {
    width: 80,
    height: 80,
  },
  appName: {
    fontSize: 24,
    fontWeight: 'bold',
    marginTop: 10,
  },
  signUpTitle: {
    fontSize: 18,
    color: '#666',
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
  registerButton: {
    backgroundColor: '#3897f0',
    borderRadius: 8,
    paddingVertical: 15,
    alignItems: 'center',
    marginTop: 10,
  },
  disabledButton: {
    backgroundColor: '#b2dffc',
  },
  registerButtonText: {
    color: '#fff',
    fontWeight: '600',
    fontSize: 16,
  },
  loginContainer: {
    flexDirection: 'row',
    marginTop: 30,
    justifyContent: 'center',
  },
  loginText: {
    fontSize: 14,
    color: '#333',
  },
  loginLink: {
    fontSize: 14,
    fontWeight: '600',
    color: '#3897f0',
  },
  termsText: {
    fontSize: 12,
    color: '#999',
    textAlign: 'center',
    marginTop: 20,
    paddingHorizontal: 30,
  },
});