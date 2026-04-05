import * as React from 'react';
import Grid from '@mui/joy/Grid';
import Box from '@mui/joy/Box';
import Button from '@mui/joy/Button';
import Snackbar from '@mui/joy/Snackbar';
import NorthWestIcon from '@mui/icons-material/NorthWest';
import NorthEastIcon from '@mui/icons-material/NorthEast';
import NorthIcon from '@mui/icons-material/North';
import SouthIcon from '@mui/icons-material/South';
import SouthEastIcon from '@mui/icons-material/SouthEast';
import SouthWestIcon from '@mui/icons-material/SouthWest';
const cloud = import.meta.env.VITE_CLOUD_URL;

export default function PositionedSnackbar({ open, onClose, message, color = 'primary'}) {
    const [state] = React.useState({
        vertical: 'top',
        horizontal: 'center',
      });
      const { vertical, horizontal } = state;

  const handleClick = (newState) => () => {
    setState({ ...newState, open: true });
  };

  const handleClose = () => {
    setState({ ...state, open: false });
  };

  const buttons = (
    <React.Fragment>
      <Box sx={{ display: 'flex', justifyContent: 'center' }}>
        <Button
          variant="plain"
          startDecorator={<NorthIcon />}
          onClick={handleClick({ vertical: 'top', horizontal: 'center' })}
          sx={{ flexDirection: 'column', gap: 1, '--Button-gap': 0 }}
        >
          Top Center
        </Button>
      </Box>
      <Grid container sx={{ justifyContent: 'center' }}>
        <Grid size={6}>
          <Button
            variant="plain"
            startDecorator={<NorthWestIcon />}
            onClick={handleClick({ vertical: 'top', horizontal: 'left' })}
          >
            Top Left
          </Button>
        </Grid>
        <Grid sx={{ textAlign: 'right', mb: 2 }} size={6}>
          <Button
            variant="plain"
            endDecorator={<NorthEastIcon />}
            onClick={handleClick({ vertical: 'top', horizontal: 'right' })}
          >
            Top Right
          </Button>
        </Grid>
        <Grid size={6}>
          <Button
            variant="plain"
            startDecorator={<SouthWestIcon />}
            onClick={handleClick({ vertical: 'bottom', horizontal: 'left' })}
          >
            Bottom Left
          </Button>
        </Grid>
        <Grid sx={{ textAlign: 'right' }} size={6}>
          <Button
            variant="plain"
            endDecorator={<SouthEastIcon />}
            onClick={handleClick({ vertical: 'bottom', horizontal: 'right' })}
          >
            Bottom Right
          </Button>
        </Grid>
      </Grid>
      <Box sx={{ display: 'flex', justifyContent: 'center' }}>
        <Button
          variant="plain"
          endDecorator={<SouthIcon />}
          onClick={handleClick({ vertical: 'bottom', horizontal: 'center' })}
          sx={{ flexDirection: 'column', gap: 1, '--Button-gap': 0 }}
        >
          Bottom Center
        </Button>
      </Box>
    </React.Fragment>
  );

  return (
    <Box>
    <Snackbar
      anchorOrigin={{ 
        vertical: 'bottom', 
        horizontal: 'right' 
      }}
      open={open}
      onClose={onClose}
      color={color}
      variant="soft"
      size="sm"
      autoHideDuration={2500}
      sx={{
        backgroundColor: color === 'danger' ? '#ff4444' : '#141414',
        color: 'white',
        borderRadius: '8px',
        minWidth: '200px'
      }}
    >
      {message}
    </Snackbar>
  </Box>
  );
}
