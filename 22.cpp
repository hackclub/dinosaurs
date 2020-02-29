#include<stdio.h>
#include<stdlib.h>
int main( ) 
{ 
int n, * p, i , sum=0;
printf("Enter N value\ n" );
scanf(" %d", &n);
p=(int*)malloc(n*sizeof(int));
if(p!=NULL) 

{ 
printf ("Enter Nnumbers\ n" ); 
for(i =0; i <n; i ++) 
scanf (" %d", p+i ); 
for(i =0; i <n; i ++) 
sum+=* (p+i); 
printf("Sum of %d numbers is %d\ n" , n, sum); 
free(p); 
p=NULL;
} 
 else 
 printf(" Dynamic memory allocati onf ai l ed\ n" );
 return 0; 
}
