/*--------------------------------*- C++ -*----------------------------------*\
  =========                 |
  \\      /  F ield         | OpenFOAM: The Open Source CFD Toolbox
   \\    /   O peration     | Website:  https://openfoam.org
    \\  /    A nd           | Version:  10
     \\/     M anipulation  |
\*---------------------------------------------------------------------------*/
FoamFile
{
    format      ascii;
    class       volVectorField;
    object      nut;
}
// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

dimensions      [0 2 -1 0 0 0 0];

internalField   uniform (0 0 0);

boundaryField
{

    outerwall-part-sys_solid
    {
        type           /* type */;
        value          /* value */;
    }

    outerwall-part-sys_solid1
    {
        type           /* type */;
        value          /* value */;
    }

    outerwall-part-sys_solid11
    {
        type           /* type */;
        value          /* value */;
    }

    outerwall-part-sys_solid111
    {
        type           /* type */;
        value          /* value */;
    }

    innerwall-part-sys_solid
    {
        type           /* type */;
        value          /* value */;
    }

    innerwall-part-sys_solid1
    {
        type           /* type */;
        value          /* value */;
    }

    innerwall-part-sys_solid11
    {
        type           /* type */;
        value          /* value */;
    }

    innerwall-part-sys_solid111
    {
        type           /* type */;
        value          /* value */;
    }

}

// ************************************************************************* //

